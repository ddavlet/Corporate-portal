# ТЗ: еженедельный отчёт для инвесторов в портале

Спека: [`specs/2026-10-26-investor-weekly-report-design.md`](../specs/2026-10-26-investor-weekly-report-design.md). Формулы, текст и поведение берутся оттуда. Это ТЗ задаёт порядок работ, файлы и критерии приёмки.

Ветка: `dev/investor-weekly-report`, один PR. Работу вести в свободном worktree-слоте. Локально тесты не запускать: проверяют GitHub Actions `Backend Tests` и `Vitest`.

## Исходные данные для приёмки

Перед началом снять эталоны с черновика n8n `invReportAllTnt1` (Code-узел «Собрать отчёты») на две даты:

| Тенант | 23.10.2026 | 26.10.2026 |
|---|---|---|
| `lemonaqua` (цель 34,72) | эталон A1 | эталон A2 |
| `lemonfit` (цель 21,4, с февраля) | эталон O1 | эталон O2 |
| `lemonhavo` (без цели, выплат нет) | — | эталон H2 |

Эталоны в тестах — это **фикстуры с синтетическими данными**, построенные по тем же правилам, а не дамп продовой базы. Сверку с продом делаем на шаге «Переход» через `--dry-run`.

## Задачи

### 1. Модели и миграция

Файлы: `investments/models.py`, `investments/migrations/00NN_invest_report.py` (вручную, `# hand-written: branch-only models`), `investments/admin.py`.

- `InvestReportConfig` и `InvestReportDispatch` — поля, default и индексы по спеке.
- Частичный `UniqueConstraint(tenant, report_date)` с условием `kind='scheduled' AND status='sent'`.
- Admin: оба класса только для чтения журнала (`InvestReportDispatch` без add/change/delete).

Приёмка: миграция применяется на чистой базе в CI, `makemigrations --check` не находит изменений.

### 2. Курс «на дату или ближайший предыдущий»

Файл: `investments/services.py`, новая функция (существующие `usd_uzs_equivalents*` не менять — OCP).

```python
def usd_uzs_rate_on_or_before(rate_date, *, cache: dict | None = None) -> Decimal | None
```

- Ищет `CbuExchangeRate` с `date ≤ rate_date`, самый поздний. Если его нет — берёт самый ранний в архиве. Если архив пуст — `None`.
- Без сетевых запросов.
- `cache` нужен, чтобы при сотне строк не делать сотню запросов. Допустимо одним запросом загрузить все курсы за диапазон дат отчёта.

Приёмка: тесты на точную дату, выходной день (берётся пятница), дату раньше архива, пустой архив.

### 3. Расчёт отчёта

Файл: `investments/investor_report.py`.

- `@dataclass(frozen=True) InvestorReport` — все метрики из таблицы спеки, суммы `Decimal`, а также `last_payouts: list[Payout]`.
- `build_investor_report(*, tenant, today: date, config) -> InvestorReport`. Только чтение ORM, два запроса (инвестиции и выплаты тенанта) плюс курсы.
- `config` — объект с полями `target_annual_rate`, `start_month`, `last_payouts_count`, `late_payment_day`. Подходит и модель, и dataclass из query-параметров preview.

Приёмка — тесты из раздела «Тесты» спеки, пункты про расчёт, курс, `start_month`, правило 25-го числа, дефицит и последние выплаты.

### 4. Форматтер

Файл: `investments/investor_report_formatter.py`.

- `format_investor_report(report, *, tenant_name) -> str` — HTML по шаблону спеки.
- Хелперы `_num`, `_usd`, `_pct`, `_pp`: неразрывный пробел между разрядами, запятая, «−».

Приёмка: тексты на фикстурах совпадают посимвольно с эталонами A1/A2/O1/O2/H2 (эталоны лежат строками в тесте). Тест на экранирование `<` и `&` в названии тенанта.

### 5. Отправка и cron

Файлы:
- `investments/investor_report_jobs.py`
- `investments/management/commands/run_invest_reports.py`
- `backend_v2/cron/crontab`
- `investments/apps.py` (`_NO_POLLER_COMMANDS`)

Функции:
- `send_report(*, tenant, config, today, kind, recipient_id, user=None) -> InvestReportDispatch`. Отправляет через `TelegramDispatcher(tenant).send(action=get_requests_messaging_gateway_settings(tenant=tenant).send_action, recipient_id=…, text=…)` и пишет журнал. Исключения логируются (`logger.exception`) и превращаются в `failed`, наружу не пробрасываются.
- `process_due_reports(now) -> int`: отбор конфигов по спеке (активен, тенант активен, модуль включён, день недели и час совпали, `scheduled`/`sent` за сегодня ещё нет). Ошибка одного тенанта не мешает остальным.
- Команда: `--now=ISO`, `--tenant=<subdomain>`, `--dry-run` (печать текстов, без отправки и записи).
- Crontab: `0 * * * * root cd /app && python manage.py run_invest_reports >> /proc/1/fd/1 2>&1`.

Приёмка (gateway замокан `cash_withdrawals.fixtures.gateway_ok`):
- понедельник 10:00 по Ташкенту → одна отправка в `chat.chat_id`, `sent`, ссылка на `TelegramMessage`;
- 09:00 или вторник → ничего;
- повторный запуск в тот же час → без дубля;
- gateway вернул ошибку → `failed`;
- модуль выключен, тенант неактивен, конфиг неактивен → ничего;
- `--dry-run` → в БД ничего нет, в stdout текст;
- `apps/common/test_cron_env.py` (если он проверяет состав crontab) обновлён.

### 6. API

Файлы: `investments/serializers.py`, `investments/services.py` (`get_report_config_payload`, `save_report_config`), `investments/views.py`, `investments/urls.py`.

Эндпоинты, права и поведение — по таблице спеки. Валидация:
- чат принадлежит тенанту и активен;
- `is_active=True` без чата → 400;
- `weekday` 0–6, `send_hour` 0–23, `start_month` 1–12 или null, `target_annual_rate` 0–1000 или null, `last_payouts_count` 0–10, `late_payment_day` 1–31;
- preview: `date` не позже сегодняшней; параметры из query перекрывают сохранённые;
- send-test без `telegram_chat_id` у пользователя → 400 «Привяжите Telegram в профиле»;
- send-now без активного чата → 400.

Приёмка: API-тесты на права (обычный пользователь модуля не может PUT config и send-now), на каждую валидацию и на формат ответа preview `{text, metrics}`.

### 7. Фронтенд

Файлы:
- `frontend_v2/src/lib/api.ts` — 6 функций и типы;
- `frontend_v2/src/ui/settings/InvestmentReportConfigPage.tsx`;
- `frontend_v2/src/settings/settingsModules.tsx` — пункт «Отчёт для инвесторов», группа `investments`, иконка из `@ant-design/icons`;
- `frontend_v2/src/routes/App.tsx` — маршрут `settings/investment-report`;
- `frontend_v2/src/ui/SettingsPage.tsx` — доступ (как у страницы уведомлений по инвестициям, но только для admin/director).

Требования:
- Блоки страницы — по спеке. Предпросмотр обновляется с debounce 500 мс при изменении параметров расчёта или даты.
- HTML предпросмотра рендерится через безопасный разбор: разрешён только `<b>`, остальное выводится текстом.
- «Отправить в группу сейчас» — через `Modal.confirm` с названием группы.
- Таблица отправок: дата, тип, статус, группа, ошибка.
- При 403/404 — `Result` вместо формы.

Приёмка: тесты Vitest из спеки.

### 8. Документация

- `docs/PRODUCT_OVERVIEW.md` — абзац про отчёт в разделе инвестиций.
- В описании PR — чек-лист «Переход с n8n» из спеки.

## Переход с n8n (после мержа и деплоя — делает пользователь)

1. В портале у каждого тенанта выбрать группу. Добавить бота тенанта в группу, если его там нет.
2. Задать цели: AQUA — 34,72; ONE — 21,4 и `start_month = 2`; Havo — без цели.
3. `run_invest_reports --dry-run --now=<понедельник 10:00>` сравнить с выводом `invReportAllTnt1` на ту же дату. Отличий быть не должно.
4. «Отправить мне» по каждому тенанту.
5. Включить конфиги и в тот же день до 10:00 выключить в n8n `Investments report` и `Отчёт для инвесторов — все тенанты`.
6. После первого понедельника проверить журнал отправок.

## Definition of Done

- [ ] `Backend Tests` и `Vitest` зелёные.
- [ ] Тексты на эталонных фикстурах совпадают с черновиком n8n посимвольно.
- [ ] Отчёт уходит ботом тенанта в группу тенанта. Сообщение есть в `TelegramMessage`/истории и в журнале отчёта.
- [ ] Плановая отправка не дублируется при повторном запуске cron.
- [ ] Ошибка одного тенанта не мешает отправке другим.
- [ ] Настройки, предпросмотр, «Отправить мне» и «Отправить в группу» работают из UI. Без прав доступа и при выключенном модуле страница показывает понятную заглушку.
- [ ] Новых точек интеграции и новых зависимостей нет. Существующие функции `services.py` не изменены.

## Не входит

Исправление `run_invest_notifications` (обход диспетчера, cron раз в день при фильтре по `notify_hour`, дата по UTC, отсутствие проверки чата и прав) — отдельный `fix/` PR. Подробности в разделе «Замечено по соседнему коду» спеки.
