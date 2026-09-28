# Подтверждение поступления наличных после снятия с банка

Переносит из n8n в портал ветку «Снятие наличных» (Switch1 → `Cash Receipt Approval` → `HTTP Cash Revenue` → `Cash Notification Text` → `Send Cash Notification`).

## Цель

1. Когда заявка «снятие наличных» становится `PAYED`, портал отправляет в Telegram карточку «Ожидается поступление в кассу» с кнопкой «✅ Деньги получены».
2. Нажатие кнопки (только уполномоченными пользователями) создаёт доход кассы `cashier.CashRevenue`.
3. Если за N дней никто не подтвердил, получателям предупреждений каждые M дней приходит напоминание, пока ожидание не закроют. Ожидание не «сгорает», в отличие от 3-дневного `sendAndWait` в n8n.
4. После подтверждения портал отправляет в n8n событие `new-cash-revenue`, и n8n публикует сообщение «Движение денежных средств», как делает это для остальных движений.
5. Всё настраивается по тенанту: правила-триггеры, касса, получатели карточки и предупреждений, сроки.

## Решения (согласованы)

| Вопрос | Решение |
|---|---|
| Где живёт код | Новый модуль `backend_v2/apps/modules/cash_withdrawals/` |
| Кто шлёт «Движение денежных средств» | n8n по новому событию `/n8n/events/new-cash-revenue` от портала |
| Кто может подтвердить | Пользователи из настройки; сверка `telegram_from_id` нажавшего |
| Куда уходит карточка | Как платёжный этап согласования: если указана группа (`TenantTelegramChat`) — одна карточка в группу, иначе каждому пользователю в личку |
| Сумма | Только полная сумма заявки; расхождения правятся в портале вручную |
| Кнопки в карточке | Одна: «✅ Деньги получены» |
| Предупреждение | Первое через N дней, затем каждые M дней; **без кнопки**; свои получатели (пользователи + группа) |
| UI в портале | Только страница настроек; списка ожиданий нет |
| Закрыть без дохода | Только Django admin action с комментарием |
| Триггер | Правила «тип оплаты + назначение платежа → касса» |
| Права на настройки | Админ/директор тенанта (`IsTenantAdminOrDirector`), как `can_manage_wallet_settings` на фронте |

## Данные (`cash_withdrawals/models.py`)

### `CashWithdrawalConfig` (OneToOne на `Tenant`)

| Поле | Тип | Default |
|---|---|---|
| `is_active` | Bool | `False` |
| `card_telegram_chat` | FK `telegram_approvals.TenantTelegramChat`, null, `SET_NULL` | — |
| `alert_telegram_chat` | FK `telegram_approvals.TenantTelegramChat`, null, `SET_NULL` | — |
| `alert_after_days` | PositiveInt | 3 |
| `alert_repeat_every_days` | PositiveInt (≥1) | 1 |
| `alert_hour` | PositiveSmallInt 0–23, Asia/Tashkent | 9 |
| `updated_at`, `updated_by` | | |

### `CashWithdrawalConfirmer`
`config` FK, `user` FK (`PROTECT`). Уникально `(config, user)`.

### `CashWithdrawalAlertRecipient`
`config` FK, `user` FK (`PROTECT`). Уникально `(config, user)`.

### `CashWithdrawalRule`
`config` FK, `payment_type` (Char, из `Request.PAYMENT_TYPE_CHOICES`), `payment_purpose` (Char, имя из `RequestPaymentPurposeConfig`), `wallet` FK `wallets.Wallet` (`PROTECT`, только `wallet_type=cash`, того же тенанта). Уникально `(config, payment_type, payment_purpose)`.

Сопоставление с заявкой идёт по строкам `Request.payment_type` / `Request.payment_purpose`: так же хранятся и сами заявки.

### `CashWithdrawalReceipt` — ожидание

| Поле | Тип | Примечание |
|---|---|---|
| `tenant` | FK | |
| `request` | OneToOne `requests.Request`, `PROTECT` | один запрос — одно ожидание |
| `wallet` | FK `wallets.Wallet`, `PROTECT` | касса из правила на момент создания |
| `amount`, `currency` | Decimal(18,2), Char | снимок из заявки |
| `status` | Char: `pending` / `confirmed` / `closed` | default `pending` |
| `confirmed_by` | FK User, null | |
| `confirmed_at` | DateTime, null | |
| `cash_revenue` | OneToOne `cashier.CashRevenue`, null, `PROTECT` | |
| `closed_by`, `closed_at`, `closed_comment` | | admin action |
| `last_alert_at` | DateTime, null | |
| `alert_count` | PositiveInt | 0 |
| `created_at` | DateTime | точка отсчёта N дней |

Индекс `(tenant, status, created_at)`.

### `CashWithdrawalMessage`
`receipt` FK, `telegram_message` OneToOne `telegram_approvals.TelegramMessage`, `kind` (`card` / `alert`). Собственная таблица модуля вместо новых `Notification.kind`: модель `telegram_approvals` не меняется. Сообщение о несовпадении валют к ожиданию не привязано (ожидания нет) и остаётся только в `TelegramMessage`/`TelegramMessageHistory`.

Миграции пишутся вручную (`# hand-written: branch-only models`), как в payroll #313: `make makemigrations` запускается на сервере с кодом `main` и новых моделей не видит.

## Поток

### 1. PAYED → ожидание
- `CashWithdrawalsConfig.ready()` регистрирует `on_request_payed` через `status_events.register_request_payed_event_handler`. Существующий код `requests` не меняется.
- `on_request_payed(request_obj)`:
  1. Нет конфига или `is_active=False` → выход.
  2. Ищем правило по `(payment_type, payment_purpose)`; нет правила → выход.
  3. Если `request.currency != rule.wallet.currency` → ожидание не создаём, `logger.error`, получателям предупреждений уходит сообщение о несовпадении валют (см. тексты).
  4. `get_or_create` ожидания по `request` (идемпотентно при повторном PAYED).
  5. `transaction.on_commit` → отправка карточки.
- Отправка карточки: если задан `card_telegram_chat` — одна карточка в группу; иначе по одной каждому подтверждающему с `telegram_chat_id`. Ошибка отправки логируется, ожидание остаётся `pending`: предупреждение всё равно придёт.

### 2. Нажатие кнопки
- `callback_data`: `cwr:<receipt_id>`.
- В `TelegramApprovalWebhookView.post` добавляется одна ветка-делегат по образцу `invest_pay:`: `if payload_str.startswith("cwr:")` → `cash_withdrawals.telegram.handle_callback(...)`. Вся логика живёт в модуле.
- Проверки: `user_id` нажавшего совпадает с `telegram_from_id` (или `telegram_chat_id`) одного из `CashWithdrawalConfirmer`, иначе в тот же чат отправляется сообщение «Нет прав на подтверждение», HTTP 403, дохода нет.
- `transaction.atomic()` + `select_for_update` по ожиданию:
  - `status != pending` → нажатая карточка перерисовывается в итоговый вид без кнопки (там уже написано, кто подтвердил), дохода нет.
  - иначе создаётся `CashRevenue`: `wallet` из ожидания, `total_sum=amount`, `currency`, `revenue_at=now`, `confirmed=True`, `operation="Наличные с банка <request.title>"`, `comment=request.description`, `external_id="cash-<request_id>"`, `source_year=None`, `created_by=нажавший`. Ожидание переходит в `confirmed`.
- `on_commit`: все карточки ожидания редактируются в «подтверждённый» вид без кнопки; вызываются обработчики `receipt_confirmed` (см. п. 3).
- Ошибка редактирования карточек только логируется: доход уже сохранён.

### 3. Событие в n8n
- `cash_withdrawals/events.py`: `register_receipt_confirmed_handler(handler)` / `dispatch_receipt_confirmed(receipt)`. Паттерн тот же, что у `status_events`: ошибка обработчика логируется и не ломает поток.
- `n8n_integration`: новый `event_handlers.notify_cash_withdrawal_received(receipt)` + регистрация в `N8NIntegrationConfig.ready()`. Транспорт и заголовки — как у `notify_request_payed` (`_build_n8n_url`, `_n8n_session`, фоновый поток).
- `POST {n8n}/n8n/events/new-cash-revenue`, тело:

```json
{
  "event": "cash_withdrawal_received",
  "cash_revenue_id": 1234,
  "external_id": "cash-8354",
  "amount": "100000000.00",
  "currency": "UZS",
  "revenue_at": "2026-09-25T14:02:11+05:00",
  "wallet_id": 13,
  "wallet_name": "Основная касса (касса)",
  "wallet_balance": "7807250.00",
  "confirmed_by": "Иван Петров",
  "request": {
    "id": 8354, "title": "...", "payment_type": "Перечисление",
    "payment_purpose": "Снятие наличных с банка", "category": "...",
    "description": "...", "vendor": "...", "company_payer": "...",
    "payed_at": 20260925, "billing_date": "2026-09-25"
  },
  "tenant": "lemonaqua"
}
```

`wallet_balance` берётся из `wallets.services` (тот же расчёт, что у `/wallet-balances/`) после коммита дохода.

### 4. Предупреждения (cron)
- Команда `run_cash_withdrawal_alerts`, строка в `backend_v2/cron/crontab` — `0 * * * *` (каждый час).
- Для каждого активного конфига, если текущий час (Asia/Tashkent) == `alert_hour`: берём `pending` ожидания, где `now - created_at ≥ alert_after_days` дней **и** (`last_alert_at` пуст **или** `today - last_alert_at.date() ≥ alert_repeat_every_days`).
- Отправка: в `alert_telegram_chat`, если задан, иначе каждому `CashWithdrawalAlertRecipient` в личку. Затем `last_alert_at=now`, `alert_count += 1`.
- Сравнение по дате `last_alert_at` исключает повтор в тот же день при повторном запуске команды.

### 5. Закрытие без дохода (admin)
- `CashWithdrawalReceiptAdmin`: список с фильтрами по тенанту/статусу; поле `closed_comment` редактируется в карточке ожидания; action «Закрыть без дохода» закрывает выбранные `pending` с заполненным `closed_comment`, остальные пропускает с сообщением.
- Статус меняется на `closed`, заполняются `closed_by/at/comment`, в заявку пишется `RequestComment` от пользователя pk=1 («Система»): «Ожидание поступления наличных закрыто без дохода: <комментарий>». Карточки деактивируются с пометкой «Закрыто без дохода».

## Тексты сообщений (HTML, `formatter.py` модуля)

**Карточка:**
```
💸 Ожидается поступление в кассу

Сумма: 100 000 000 UZS
Касса: Основная касса
Заявка №8354 · Снятие наличных с банка
Комментарий: Снятие денег с банка на расходы выдачу зарплат

Подтвердить могут: Иван П., Мария С.

[✅ Деньги получены]
```
- «Заявка №…» — ссылка на заявку в портале, как в карточках согласования.
- «Комментарий» (`request.description`) не выводится, если пуст.
- «Касса» — имя кассы без суффикса «(касса)», если он есть.

**После подтверждения** (карточка редактируется, кнопка снимается):
```
✅ Поступило в кассу
100 000 000 UZS → Основная касса
Подтвердил: Иван П. · 25.09.2026 14:02
Заявка №8354 · Снятие наличных с банка
```

**Закрыто без дохода** (карточка редактируется):
```
⛔ Закрыто без дохода
100 000 000 UZS · Заявка №8354 · Снятие наличных с банка
Причина: <комментарий>
```

**Предупреждение:**
```
⚠️ Деньги не оприходованы в кассу — 3 дн.

Заявка №8354 оплачена 25.09.2026 (Снятие наличных с банка)
Сумма: 100 000 000 UZS → Основная касса
Дохода в кассе нет — никто не подтвердил получение.

Проверьте, поступили ли деньги, и нажмите «✅ Деньги получены» в исходной карточке.
Ответственные: Иван П., Мария С.
```
«3 дн.» — фактическое число дней с `created_at`.

**Несовпадение валют:**
```
⚠️ Заявка №8354 (Снятие наличных с банка): валюта USD не совпадает с кассой «Основная касса» (UZS). Ожидание не создано — проверьте правило в настройках.
```

**Ответы на нажатие:** tg-gateway отвечает на callback пустым `answer()` и не передаёт текст, поэтому отказ «Нет прав на подтверждение» уходит обычным сообщением в тот же чат (как ответы slash-команд). Для «уже подтверждено» отдельного сообщения нет: карточка перерисовывается в итоговый вид.

## API и фронтенд

### Backend
- `cash_withdrawals/urls.py`, подключение в корневом роутинге: `GET/PUT /api/cash-withdrawals/config/`.
- `GET` возвращает конфиг и справочники для формы: кандидаты-пользователи (активные участники тенанта с флагом `has_telegram`), чаты тенанта, кассы (`wallet_type=cash`), пары «тип оплаты → назначения» из `RequestFormConfig`.
- `PUT` заменяет конфиг целиком (подтверждающие, получатели, правила) в одной транзакции. Валидация: кассы и чаты принадлежат тенанту, кассы типа cash, `alert_repeat_every_days ≥ 1`, `alert_hour` в 0–23, при `is_active=True` есть хотя бы одно правило и хотя бы один подтверждающий.
- Права: `IsAuthenticated, IsTenantAdminOrDirector`.

### Frontend
- `src/lib/cashWithdrawals.ts` (или раздел в `lib/api.ts` по текущему паттерну) — `getCashWithdrawalConfig` / `saveCashWithdrawalConfig`.
- `src/ui/settings/CashWithdrawalConfigPage.tsx`, маршрут `settings/cash-withdrawal-config`, ссылка в `SettingsPage` рядом с «Уведомления по инвестициям».
- Блоки: «Включено»; «Карточка подтверждения» (пользователи + группа); «Правила» (таблица «Тип оплаты · Назначение → Касса», добавить/удалить строку); «Предупреждения» (пользователи + группа, N, M, час).
- У пользователя без привязанного Telegram — тег-предупреждение, как в `RequestApprovalConfigPage`.
- Если эндпоинт недоступен (модуль отключён) или 403 — `Result`/`Alert` с понятным текстом вместо формы.

## Бэкфилл

`python manage.py backfill_cash_withdrawal_receipts --tenant=<subdomain> --since=YYYY-MM-DD [--apply] [--no-send]`
- Находит заявки `PAYED` с `payed_at ≥ since`, подходящие под правила тенанта, у которых нет ни ожидания, ни `CashRevenue(external_id="cash-<id>")`.
- По умолчанию dry-run (печатает список). С `--apply` создаёт ожидания и отправляет карточки (без отправки при `--no-send`).
- Make-таргет `make backfill-cash-withdrawals TENANT=... SINCE=... [APPLY=1]` по образцу `reassign-unmatched`.

## Переход с n8n

1. Деплой, миграции.
2. Настроить в портале правила и получателей (lemonaqua: «Перечисление · Снятие наличных с банка → Основная касса (id 13)»), включить.
3. В n8n: выключить ветку Switch1 «Снятие наличных» и добавить workflow на `new-cash-revenue` с форматированием «Движение денежных средств» (текст из `Cash Notification Text`, остаток брать из `wallet_balance` события).
4. Бэкфилл dry-run → проверка → `--apply` для потерянных случаев.

После отключения ветки n8n доходы по снятиям не создаёт — единственный источник портал, поэтому отдельной защиты от «дохода из n8n» в обработке кнопки нет. Исторические доходы, созданные n8n (`external_id="cash-<id>"`), учитывает только бэкфилл.

Примечание: уникальный индекс `CashRevenue(tenant, external_id, source_year)` при `source_year=NULL` дубли не блокирует (NULL в Postgres различны), поэтому от двойного дохода защищают `OneToOne(request)` у ожидания и `select_for_update`, а не этот индекс.

## Ошибки и крайние случаи

| Случай | Поведение |
|---|---|
| Нет правила / модуль выключен | Ничего не делаем |
| Валюта заявки ≠ валюта кассы | Ожидание не создаётся, `logger.error`, сообщение получателям предупреждений |
| Карточка не отправилась | Ожидание `pending`, `logger.exception`; сработает предупреждение |
| У всех подтверждающих нет Telegram и нет группы | Как выше; на странице настроек это видно заранее |
| Нажал чужой | Сообщение «Нет прав на подтверждение» в чат, 403, дохода нет |
| Двойное нажатие / гонка | `select_for_update`; второй — карточка перерисовывается, дохода нет |
| Ошибка события в n8n | Лог, на доход не влияет, повторов нет |
| Заявку вывели из PAYED | Ожидание не трогаем автоматически; закрытие через admin |
| Повторный PAYED той же заявки | `get_or_create` — второе ожидание не создаётся |

Все внешние вызовы (gateway, n8n) логируются явно, без «тихих» `except`.

## Тесты

Backend (`cash_withdrawals/tests.py`, gateway и n8n замоканы):
- PAYED + правило → ожидание `pending`, карточка в группу; без группы — по одной в личку каждому подтверждающему.
- PAYED без правила / при выключенном конфиге → ничего.
- Несовпадение валют → ожидания нет, ушло предупреждение.
- Повторный PAYED → одно ожидание.
- Callback от подтверждающего → `CashRevenue` (сумма, касса, `created_by`, `external_id`), статус `confirmed`, карточки отредактированы, вызван `receipt_confirmed`-обработчик.
- Callback от чужого → 403, дохода нет, в чат ушло «Нет прав на подтверждение».
- Повторный callback → один доход, карточка перерисована без кнопки.
- Cron: до N дней — тишина; на N-й день в `alert_hour` — предупреждение; в тот же день повторно — нет; через M дней — снова; после `confirmed`/`closed` — нет; не в `alert_hour` — нет.
- Admin action «Закрыть без дохода» → `closed`, `RequestComment` от pk=1.
- `PUT config`: валидация чужой кассы/чата, не-cash кассы, пустых правил при `is_active=True`.
- `n8n_integration`: `notify_cash_withdrawal_received` формирует ожидаемый payload и URL `/n8n/events/new-cash-revenue`.
- Бэкфилл: dry-run ничего не создаёт; `--apply` создаёт ожидания только для заявок без дохода.

Frontend (Vitest):
- `CashWithdrawalConfigPage` рендерит форму из ответа API, добавляет/удаляет правило, отправляет корректный payload.
- Показывает предупреждение у пользователя без Telegram.
- При 403/404 показывает заглушку.

## Вне рамок

- Список ожиданий и подтверждение в портале.
- Частичное подтверждение / ввод другой суммы.
- Ветки n8n «Дивиденды» и нижняя ветка «Наличные» — остаются в n8n.
- Общий движок «ожидаемых поступлений» для других сценариев.
