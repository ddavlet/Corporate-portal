# TelegramDispatcher — единый исходящий хаб + TelegramMessage как источник истины

- **Дата:** 2026-05-29
- **Ветка:** `dev/refactor-telegram-messages` (PR 190)
- **Статус:** одобрено к реализации (без деплоя; локальное тестирование через `docker-compose.local`)

## Контекст и проблема

Отправка в `tg-gateway` сейчас — набор свободных функций (`build_gateway_payload` +
`post_messaging_gateway`/`_post_to_gateway`), а оркестрация «собрать payload → отправить →
извлечь `message_id` → сохранить» продублирована в 7 местах: requests (approvals),
tasks, notes, feedback, investments (×4 файла).

Модель `TelegramMessage` (введена в PR 190) — пассивное хранилище; реально ничего не
отправляет. Информация об отправленном сообщении у `Approval` дублируется в трёх полях
(`gateway_message_id`, `message_sent`, `message_sent_at`) и теперь ещё в `telegram_message`.

## Цель

1. **Исходящий хаб `TelegramDispatcher`** — единый класс, владеющий взаимодействием с
   gateway (send/edit/delete/deactivate) и записью `TelegramMessage`. Модули отдают только
   содержимое (текст, кнопки, recipient, ссылку на доменный объект).
2. **`TelegramMessage` — единственный источник истины** о сообщении. С `Approval`
   убираются `gateway_message_id`/`message_sent`/`message_sent_at`; все читатели переводятся
   на `telegram_message`.

### Non-goals (отдельные фазы / PR)

- **CALLBACK dispatcher** (входящий маршрутизатор webhook → модуль) — фаза 4.
- Перевод `UserRequestApproval` на источник истины.
- Любые действия с продом (деплой, серверные миграции).

## Архитектура

```
Requests→Approvals ─┐  build content (text, buttons, recipient_id, link)
Tasks ──────────────┤
investments ────────┼─►  TelegramDispatcher(tenant)  ──►  tg-gateway
notes / feedback ───┘          │ send / edit / delete / deactivate
                               ▼
                         TelegramMessage  (единственная запись о сообщении)
```

Модули владеют **содержимым**; диспетчер владеет **механикой gateway** (сборка payload через
`build_gateway_payload` + `normalize_gateway_buttons`, POST, парсинг `message_id`,
создание/обновление `TelegramMessage`, проставление OneToOne-ссылки). `TelegramMessage`
остаётся пассивной моделью (правило CLAUDE.md «модели ≠ бизнес-логика»).

## Интерфейс диспетчера (`telegram_approvals/services.py`)

```python
class TelegramDispatcher:
    def __init__(self, tenant): ...

    def send(self, *, recipient_id, text, buttons=None, link=None,
             approval_id=None, request_id=None) -> TelegramMessage | None
    def edit(self, message: TelegramMessage, *, text, buttons=None,
             approval_id=None, request_id=None) -> TelegramMessage | None
    def deactivate(self, message: TelegramMessage, *, text,
                   approval_id=None, request_id=None) -> TelegramMessage | None
    def delete(self, message: TelegramMessage) -> None
```

- `link` — доменный объект с OneToOne `telegram_message` (Approval/Task). Диспетчер сам
  ставит `link.telegram_message = msg` и сохраняет. Для notes/feedback `link=None`.
- Возврат `None` при сбое gateway — graceful degradation (как сейчас).
- Bot token / URL резолвятся внутри по `tenant` (как сейчас в `get_tenant_bot_token` /
  `_resolve_gateway_url_for_tenant`).

## Модель: `TelegramMessage` как источник истины

Убираем с `Approval`:

| Было на `Approval`              | Стало                                        |
|---------------------------------|----------------------------------------------|
| `gateway_message_id`            | `approval.telegram_message.message_id`       |
| `message_sent` (bool)           | `approval.telegram_message_id is not None`   |
| `message_sent_at`               | `approval.telegram_message.sent_at`          |
| индекс `approvals_message_sent_idx` | заменяется фильтром `telegram_message__isnull` (FK уникально проиндексирован) |

## Карта читателей (перевести всё — иначе сломается)

| Место                                   | Сейчас                                          | Станет                                    |
|-----------------------------------------|-------------------------------------------------|-------------------------------------------|
| `views.py` callback identity            | `stored_message_id=approval.gateway_message_id` | `…telegram_message.message_id`            |
| `views.py` callback set-on-None         | пишет 3 поля                                     | создаёт/линкует `TelegramMessage`         |
| `services.py` dispatch-фильтр           | `message_sent=False`                             | `telegram_message__isnull=True`           |
| `services.py` edit/deactivate guard     | `if not approval.gateway_message_id`             | `if approval.telegram_message_id is None` |
| `services.py` refresh-фильтр            | `message_sent=True, gateway_message_id__isnull=False` | `telegram_message__isnull=False`     |
| `services.py` resend                    | сброс `message_sent=False, gateway_message_id=None` | отвязка `telegram_message=None`        |
| `approval_workflow.py:228` lookup       | `filter(gateway_message_id=message_id)`          | `filter(telegram_message__message_id=…)`  |
| `approval_workflow.py:47-55` фильтр-параметр | `message_sent`                              | `telegram_message__isnull`                |
| `approval_bootstrap.py` создание        | `gateway_message_id=None, message_sent=False`    | поля убраны (default null)                |
| `apply_gateway_message_lifecycle`       | пишет 3 поля approval                             | заменяется логикой диспетчера             |

## Backfill-миграция (критично)

Существующие approvals имеют `gateway_message_id`/`message_sent_at`, но без `TelegramMessage`.
Порядок:

1. **data-миграция**: для каждого `Approval` с `gateway_message_id` создать `TelegramMessage`
   (`message_id`, `recipient_id`, `external_user_id`, `sent_at = message_sent_at or now`) и
   проставить `approval.telegram_message`.
2. **schema-миграция**: удалить 3 колонки + индекс `approvals_message_sent_idx`.

Без шага 1 «висящие» согласования потеряют `message_id` → callback identity сломается.
Миграции пишутся файлами вручную; применяются локально (`docker-compose.local`), не на проде.

## API / фронт — обратная совместимость (нулевой риск UI)

`ApprovalSerializer` отдаёт `gateway_message_id`/`message_sent`/`message_sent_at`, фронт
(`RequestDetailModal.tsx`) их читает. Заменяем на `SerializerMethodField`, вычисляемые из
`telegram_message`:
- `message_sent` → `obj.telegram_message_id is not None`
- `message_sent_at` → `obj.telegram_message.sent_at`
- `gateway_message_id` → `obj.telegram_message.message_id`

Контракт API не меняется → фронт без правок.

## Фазы реализации

- **Фаза 1 (сейчас):** `TelegramDispatcher` + перевод requests-пути на него + `TelegramMessage`
  как источник истины для `Approval` (backfill + drop колонок + читатели + сериализатор) + тесты.
- **Фаза 2:** adoption диспетчера в tasks / notes / feedback.
- **Фаза 3:** investments (оба approval-типа) — диспетчер + источник истины.
- **Фаза 4:** CALLBACK dispatcher (входящий хаб) — отдельный дизайн.

Внутри Фазы 1 — два безопасных шага: (1) behaviour-preserving рефактор (диспетчер +
маршрутизация requests, поля пока поддерживаются), (2) flip источника истины (backfill,
читатели, drop колонок).

## Тестирование

- Существующие тесты согласования переписать на `telegram_message`.
- Lifecycle-тесты (мои из 0054-коммита) — на источник истины.
- Тест backfill-миграции (approval с `gateway_message_id` → создаётся `TelegramMessage`).
- Round-trip callback по `telegram_message.message_id` (approve + reject).
- Прогон — в CI (`Backend Tests`) и локально пользователем.

## Риски

Самые чувствительные: **callback identity**, **resend**, **dispatch/refresh-фильтры** — все
завязаны на удаляемые поля. Каждая перечислена в карте читателей и покрыта тестами. API
стабилен (computed-поля). Прод защищён двухступенчатой backfill-миграцией + отсутствием деплоя.

## Ограничения

- Прод не трогаем: без `make deploy`, без `make makemigrations` (серверная), без SSH.
- Миграции — только рукописные файлы; пользователь применяет локально (`docker-compose.local`).
- Локальный прогон тестов агентом запрещён (правило проекта) — верификация через CI и
  пользователя.
