# Касса в портале (cash_desk) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести из n8n «New Payed Request» в портал создание прихода по переводу между кассами и сообщение «Движение денежных средств» в кассовую Telegram-группу — одинаково для всех тенантов.

**Architecture:** Новый Django-модуль `backend_v2/apps/modules/cash_desk/` регистрирует обработчик оплаты заявки (`requests.status_events`). Для наличных заявок он в транзакции оплаты создаёт приход по переводу (по структурной ссылке `CashRegisterTransferTarget`, с fallback на текст описания) и строку журнала `CashDeskMessage`, а в `on_commit` формирует HTML-сообщение с остатками касс и отправляет через `TelegramDispatcher`. Фронтенд передаёт кассу-получатель и сумму зачисления при создании перевода; страница настроек — по образцу «Снятия наличных».

**Tech Stack:** Django 5.2 + DRF, React + antd, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-06-cash-desk-notifications-design.md`

## Global Constraints

- Тесты локально **не запускать** (CLAUDE.md): проверка — GitHub Actions «Backend Tests» и «Vitest» после `make push` / PR. Шаги «run test» ниже = push и ждать CI.
- Миграции пишутся вручную (ветка), `# hand-written`, зависимости — последние миграции: `cashier 0014_drop_redundant_tenant_indexes`, `requests 0067_request_invest_payment_types`, `telegram_approvals 0006_drop_redundant_indexes`, `tenants 0026_tenant_payroll_payout_mode`, `wallets 0007_bankaccount_account_type`, `AUTH_USER_MODEL`.
- Никаких удалений данных; миграции данных — только `get_or_create`, существующие строки не менять.
- OCP: рабочие модули (`requests`, `cash_withdrawals`, `n8n_integration`, `wallets`) не переписывать; только импорт их публичных функций.
- `CashRevenue`: `external_id = f"cash-{request.id}"` (max_length 20), `source_year` — год по Ташкенту (`TASHKENT_TZ`, как в `cash_withdrawals/services.py:160-176`), `created_by` — `User pk=1`, `confirmed=True`.
- Константа назначения: `TRANSFER_PURPOSE = "Перевод между кассами"` (своя в `cash_desk`, значение как во фронте `CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE`).
- Наличные = `canonical_payment_type(request.payment_type) == Request.PAYMENT_TYPE_CASH` (`requests/payment_type_families.py`).
- Обработчик payed никогда не роняет оплату: своя `transaction.atomic()`, `logger.exception`, отправка в `transaction.on_commit`.
- Тексты сообщений — HTML, все пользовательские значения через `html.escape`. Пустые «Получатель»/«Комментарий»/«Категория»/«Плательщик» → «—».
- UI: antd, иконки `@ant-design/icons`, API-вызовы только в `src/lib/*`.

## Review Focus

- Имя кассы в описании с суффиксом «(UZS)» и лишними пробелами/регистром (HAVO #8907) → fallback находит кассу. Тест в Task 4.
- Наличная заявка без `CashExpense req-<id>` (режим оплаты `callback`) → касса из `wallet_ref`/по умолчанию для валюты, сообщение всё равно уходит. Тест в Task 6.
- `<`, `>`, `&` в получателе/описании/назначении → экранируются, сообщение не ломает HTML. Тест в Task 5.
- Затронутая касса неактивна (`anchor_is_active=False`) → всё равно показана и выделена; прочие неактивные скрыты. Тест в Task 5.
- n8n уже создал `cash-<id>` (с любым `source_year`) → портал второй приход не создаёт. Тест в Task 4.

---

### Task 1: Модуль, модели и API настроек

**Files:**
- Create: `backend_v2/apps/modules/cash_desk/{__init__.py,apps.py,registry.py,models.py,admin.py,serializers.py,services_config.py,views.py,urls.py,fixtures.py,test_config_api.py}`, `migrations/{__init__.py,0001_initial.py}`
- Modify: `backend_v2/config/settings.py` (INSTALLED_APPS после `apps.modules.cash_withdrawals`), `backend_v2/config/urls.py` (`path("api/cash-desk/", include("apps.modules.cash_desk.urls"))` рядом с cash-withdrawals)

**Interfaces:**
- Produces:
  - `CashDeskConfig(tenant OneToOne related_name="cash_desk_config", is_active Bool default False, telegram_chat FK TenantTelegramChat null SET_NULL related_name="cash_desk_configs", updated_at auto_now, updated_by FK User null PROTECT)`, `db_table="cash_desk_configs"`.
  - `CashRegisterTransferTarget(tenant FK, request OneToOne Request related_name="cash_transfer_target", to_wallet FK Wallet PROTECT, to_amount Decimal(18,2), created_at, updated_at)`, `db_table="cash_register_transfer_targets"`.
  - `CashDeskMessage(tenant FK, request OneToOne Request related_name="cash_desk_message", kind Choices TRANSFER="transfer"/EXPENSE="expense", status Choices PENDING/SENT/FAILED/SKIPPED, telegram_message OneToOne TelegramMessage null SET_NULL, error Text blank, revenue_error Text blank, created_at, updated_at)`, `db_table="cash_desk_messages"`.
  - `services_config.get_active_config(tenant) -> CashDeskConfig | None`, `config_payload(tenant) -> dict` (`{is_active, telegram_chat_id, options: {telegram_chats: [{id, name}]}}`), `save_config(*, tenant, data, actor) -> None`.
  - `GET/PUT /api/cash-desk/config/` (`IsAuthenticated, IsTenantAdminOrDirector`).
  - `fixtures.CashDeskFixtures.make_fixtures()` → `self.tenant` (subdomain `lemonaqua`, host `lemonaqua.example.com`), `self.admin`, `self.group` (chat_id `-100500`), `self.config` (active, group), `self.main` / `self.safe` (cash wallets UZS «Основная касса (касса)» по умолчанию, «Сейф»), `self.usd` (USD «Касса USD»), `make_request(**overrides)` (PAYED, «Наличные», `payed_at=20261106`, amount 1 500 000).
- AppConfig `CashDeskConfig` name `apps.modules.cash_desk`, label `cash_desk`, verbose_name «Касса»; `ready()` пока пустой (Task 6 регистрирует обработчик). `registry.py`: `MODULE_KEY = "cash_desk"`, `display_name = "Касса: уведомления"`. Admin: три модели, `CashDeskMessage` read-only, list_display с status/error.

- [ ] **Step 1: Тесты `test_config_api.py`** (APITestCase, `HTTP_HOST=self.host`):
  - `test_get_returns_defaults_and_active_chats` — без конфига: `is_active False`, `telegram_chat_id None`, `options.telegram_chats == [{"id": group.id, "name": "Касса Aqua"}]` (неактивный чат не попадает).
  - `test_put_saves_config` — PUT `{is_active: true, telegram_chat_id: group.id}` → 200, в БД сохранено, `updated_by=admin`.
  - `test_put_rejects_foreign_chat` — чат другого тенанта → 400 по `telegram_chat_id`.
  - `test_non_admin_forbidden` — участник без роли admin/director → 403.
- [ ] **Step 2: Модели, миграция 0001 (вручную), admin, serializer (`CashDeskConfigWriteSerializer`: `is_active` Bool, `telegram_chat_id` Int null), сервис, view, urls, settings, корневой url.**
- [ ] **Step 3: Commit** `feat(cash_desk): модуль «Касса», модели и API настроек`

### Task 2: Миграция данных — кассовые группы и настройки тенантов

**Files:**
- Create: `backend_v2/apps/modules/cash_desk/migrations/0002_seed_cash_groups.py`, `backend_v2/apps/modules/cash_desk/test_seed_migration.py`

**Interfaces:**
- Produces: `SEED: tuple[tuple[str, str, str], ...]` (subdomain, chat_id, имя для новой группы) и функция `seed(apps, schema_editor)` в модуле миграции; reverse — `migrations.RunPython.noop`.

Значения (сверены с n8n и `tenant_telegram_chats` 2026-11-06):

| subdomain | chat_id | имя, если группы нет |
|---|---|---|
| lemonfit | `-1004412904548` | Касса LemonFit One |
| lemonaqua | `-5321395304` | Касса AQUA |
| lemonhavo | `-5456539546` | Касса HAVO |
| lemonnew | `-5457282029` | Касса NEW |
| neuron | `-1002710729577` | NM - касса |
| qulay | `-4841328641` | QULAY BOX buxgalteriyasi |

Логика: тенанта нет → пропустить; `TenantTelegramChat.get_or_create(tenant, chat_id, defaults={name, is_active: True})` (существующую строку не менять); `CashDeskConfig.get_or_create(tenant, defaults={is_active: False, telegram_chat: chat})` (существующий конфиг не менять).

- [ ] **Step 1: Тесты** (импорт функции через `importlib.import_module("apps.modules.cash_desk.migrations.0002_seed_cash_groups")`, вызов `seed(django_apps, None)`):
  - `test_creates_missing_group_and_inactive_config` — тенант `lemonnew` без чатов → создан чат `-5457282029` «Касса NEW», конфиг `is_active False` с этим чатом.
  - `test_reuses_existing_group_without_renaming` — у `qulay` есть чат `-4841328641` с именем «X» → имя осталось «X», конфиг указывает на него, новых чатов нет.
  - `test_keeps_existing_config` — конфиг `is_active True` с другим чатом → не изменён.
  - `test_missing_tenant_is_skipped` — пустая БД → без ошибок.
- [ ] **Step 2: Миграция 0002** (зависит от 0001).
- [ ] **Step 3: Commit** `feat(cash_desk): кассовые группы и выключенные настройки для тенантов`

### Task 3: API кассы-получателя перевода

**Files:**
- Create: `backend_v2/apps/modules/cash_desk/transfer_target.py`, `test_transfer_target_api.py`
- Modify: `serializers.py`, `views.py`, `urls.py` модуля

**Interfaces:**
- Consumes: `CashRegisterTransferTarget` (Task 1).
- Produces:
  - `PUT /api/cash-desk/transfers/<int:request_id>/target/` body `{to_wallet_id: int, to_amount?: decimal}` → 200 `{request_id, to_wallet_id, to_amount, currency}`; `permission_classes=[IsAuthenticated, HasEffectiveModuleAccess]`, `module_key="requests"`.
  - `transfer_target.save_transfer_target(*, request_obj, to_wallet_id: int, to_amount: Decimal | None, user) -> CashRegisterTransferTarget` — `update_or_create` по request.
- Правила (400 c `detail` на русском): заявка не `DRAFT`; `payment_purpose != TRANSFER_PURPOSE` или не наличная; касса не cash этого тенанта; касса = `request.wallet_ref`; валюты совпадают и `to_amount` передан и `!= request.amount`; валюты различаются и `to_amount` не передан или `<= 0`. Совпадают и `to_amount` не передан → сохраняется `request.amount`. Чужая заявка (другой тенант) → 404. Пользователь не `created_by`/`requester` и не admin/director → 403.

- [ ] **Step 1: Тесты:** `test_same_currency_defaults_amount`, `test_cross_currency_requires_amount` (USD-получатель без суммы → 400; с `120` → 200, `to_amount == Decimal("120.00")`), `test_same_currency_mismatched_amount_rejected`, `test_rejects_non_draft`, `test_rejects_non_transfer_purpose`, `test_rejects_source_wallet`, `test_rejects_foreign_wallet`, `test_other_user_forbidden`, `test_put_twice_updates`.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Commit** `feat(cash_desk): API кассы-получателя и суммы зачисления`

### Task 4: Приход по переводу

**Files:**
- Create: `backend_v2/apps/modules/cash_desk/transfer_revenue.py`, `test_transfer_revenue.py`

**Interfaces:**
- Consumes: `CashRegisterTransferTarget`, `TRANSFER_PURPOSE`.
- Produces:
  - `@dataclass(frozen=True) TransferDestination(wallet: Wallet, amount: Decimal, currency: str)`
  - `class TransferDestinationError(Exception)` — сообщение на русском, пишется в `CashDeskMessage.revenue_error`.
  - `resolve_transfer_destination(request_obj) -> TransferDestination` — target, иначе fallback: строка `^В кассу:\s*(.+?)\s*(?:\(([A-Z]{3})\))?\s*$` (multiline) из `description`; поиск `CashRegister` тенанта по `name` без учёта регистра и крайних пробелов, сравнивая и с `wallet_label`-формой (без «(касса)»); 0 или >1 → ошибка; валюта кассы ≠ `request.currency` → ошибка; сумма `request.amount`.
  - `ensure_transfer_revenue(*, request_obj, destination: TransferDestination) -> tuple[CashRevenue, bool]` — если есть `CashRevenue(tenant, external_id=f"cash-{id}")` (любой `source_year`) → `(existing, False)`; иначе создать: `wallet=destination.wallet`, `total_sum=destination.amount`, `currency=destination.currency`, `operation=f"Перевод между кассами {title}"[:255]`, `comment=description`, `revenue_at=now`, `payload={"source": "cash_desk_transfer", "request_id": id}`.

- [ ] **Step 1: Тесты:** `test_target_used`, `test_cross_currency_target_amount_and_currency`, `test_fallback_by_description_with_currency_suffix` (кассы «Сейф (UZS)» в БД нет, есть «Сейф»; описание `В кассу: Сейф (UZS)` → `self.safe`), `test_fallback_ignores_case_and_spaces`, `test_fallback_unknown_register_raises`, `test_fallback_ambiguous_raises`, `test_fallback_currency_mismatch_raises`, `test_existing_n8n_revenue_not_duplicated` (заранее `CashRevenue cash-<id>` с `source_year=2025`) , `test_creates_revenue_fields` (external_id, source_year, confirmed, created_by pk=1, operation).
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Commit** `feat(cash_desk): приход в кассе-получателе при переводе`

### Task 5: Текст сообщения

**Files:**
- Create: `backend_v2/apps/modules/cash_desk/formatter.py`, `test_formatter.py`

**Interfaces:**
- Consumes: `cash_withdrawals.formatter.format_money`, `wallet_label`, `format_payed_date` (чистые функции, импорт явный).
- Produces: `build_movement_text(*, request_obj, kind: str, from_wallet: Wallet, destination: TransferDestination | None, balances: list[dict]) -> str`. `balances` — строки `balances_for_tenant_channel` (`wallet_id`, `display_name`, `current_balance`, `currency`, `anchor_is_active`).

Текст (точная копия, `\n` между строками):

```
💰 <b>Движение денежных средств</b>

🆔 <b>ID:</b> {id}
📅 <b>Дата:</b> {format_payed_date или billing_date dd.mm.yyyy}
🔄 <b>Вид движения:</b> {Расход | Перемещение}
🏦 <b>Касса:</b> {wallet_label(from)}            | 🏦 <b>Касса:</b> {from} → {to}   (перевод; без destination — только {from})

💵 <b>Сумма:</b> <code>{format_money(amount)} {currency}</code>
💱 <b>Зачислено:</b> <code>{amount} {currency}</code>   (только перевод с другой валютой)

📝 <b>Назначение платежа:</b>
{payment_purpose}
👤 <b>Получатель:</b> {vendor}
💬 <b>Комментарий:</b>
{description}

💳 <b>Категория:</b> {category}
🏢 <b>Плательщик:</b> {company_payer}

📊 <b>Остатки по всем кассам:</b>
👉 <b>{name}: {money} {cur}</b>      (затронутая касса: from и to)
🏦 {name}: {money} {cur}             (прочие)
```
Имя кассы в остатках — `display_name` без суффикса «(касса)» (тот же regex, что в `wallet_label`). Неактивные кассы скрыты, кроме затронутых.

- [ ] **Step 1: Тесты:** `test_expense_text_exact` (полное равенство строки для заявки с fixture-данными), `test_transfer_marks_both_registers`, `test_cross_currency_shows_credited_line`, `test_html_escaped` (`vendor="ООО <Рога & Копыта>"` → `&lt;Рога &amp; Копыта&gt;`), `test_empty_fields_dash`, `test_inactive_affected_register_shown_others_hidden`.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Commit** `feat(cash_desk): текст «Движение денежных средств»`

### Task 6: Обработчик оплаты и отправка

**Files:**
- Create: `backend_v2/apps/modules/cash_desk/services.py`, `messaging.py`, `test_payed_handler.py`
- Modify: `backend_v2/apps/modules/cash_desk/apps.py` (`ready()` → `status_events.register_request_payed_event_handler(on_request_payed)`)

**Interfaces:**
- Consumes: Tasks 1, 4, 5; `wallets.services.balances_for_tenant_channel`; `wallets.resolution.resolve_wallet_for_cash`; `cashier.models.CashExpense`, `CashRevenue`; `telegram_approvals.services.TelegramDispatcher`; `requests.integration_settings.get_requests_messaging_gateway_settings`.
- Produces:
  - `services.on_request_payed(*, request_obj) -> None` — не наличная / нет активного конфига → return. В `transaction.atomic()`: для перевода — `resolve_transfer_destination` + `ensure_transfer_revenue` (ошибку `TransferDestinationError` записать в `revenue_error`, `logger.error`); если у конфига нет активного чата → `logger.warning`, return; `CashDeskMessage.get_or_create(request=...)` — не создан → return (повтор); `transaction.on_commit(lambda: send_movement_message(message_id))`.
  - `services.expense_wallet_for_request(request_obj) -> Wallet` — `CashExpense(tenant, external_id=f"req-{id}").wallet`, иначе `resolve_wallet_for_cash(tenant, currency, wallet_ref_id)` + `logger.warning`.
  - `messaging.send_movement_message(message_id: int) -> None` — собирает текст (Task 5) со свежими остатками, отправляет `TelegramDispatcher(tenant).send(action=settings.send_action, recipient_id=chat.chat_id, text=..., request_id=...)`; результат `None`/исключение → `status=FAILED`, `error`; иначе `SENT` и `telegram_message`.

- [ ] **Step 1: Тесты** (`@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="")`, gateway patch `apps.modules.telegram_approvals.services.post_messaging_gateway`, `captureOnCommitCallbacks(execute=True)`, вызов через `dispatch_request_payed_event_handlers` хотя бы в первом тесте):
  - `test_cash_expense_sends_one_message` — recipient `-100500`, текст содержит «Расход» и «Основная касса», статус SENT.
  - `test_invest_cash_uses_expense_wallet` — «Инвест. наличные», `CashExpense req-<id>` на `self.safe` → «🏦 <b>Касса:</b> Сейф».
  - `test_without_cash_expense_falls_back_to_default_register`.
  - `test_transfer_creates_revenue_and_message` — «Перемещение», `CashRevenue cash-<id>` в `self.safe`.
  - `test_transfer_unresolved_still_sends_and_logs` — `revenue_error` заполнен, прихода нет, сообщение ушло.
  - `test_repeat_payed_sends_once`.
  - `test_inactive_config_does_nothing` — ни прихода, ни сообщения.
  - `test_active_without_chat_creates_revenue_only`.
  - `test_gateway_failure_marks_failed` — `side_effect=Exception` → FAILED, исключение не всплывает.
  - `test_non_cash_ignored` — «Перечисление».
- [ ] **Step 2: Реализация + регистрация в `ready()`.**
- [ ] **Step 3: Commit** `feat(cash_desk): сообщение в кассовую группу при оплате наличной заявки`

### Task 7: Фронтенд — перевод между кассами

**Files:**
- Create: `frontend_v2/src/lib/cashDeskApi.ts`, `frontend_v2/src/lib/cashRegisterTransfer.test.ts`
- Modify: `frontend_v2/src/lib/cashRegisterTransfer.ts`, `frontend_v2/src/ui/CashRegisterTransferButton.tsx` (+ `.test.tsx`), `frontend_v2/src/ui/tg/TgCashRegisterTransferPage.tsx`

**Interfaces:**
- Produces (`cashDeskApi.ts`, через `apiFetch`/`parseErrorBody`):
  - `setCashRegisterTransferTarget(requestId: number, body: { to_wallet_id: number; to_amount?: number }): Promise<void>`
  - `getCashDeskConfig(): Promise<CashDeskConfigResponse>`, `saveCashDeskConfig(dto: CashDeskConfigDto): Promise<CashDeskConfigResponse>`; `CashDeskConfigDto = { is_active: boolean; telegram_chat_id: number | null }`, `CashDeskConfigResponse = CashDeskConfigDto & { options: { telegram_chats: Array<{ id: number; name: string }> } }`.
- `CashRegisterTransferInput` получает `toAmount?: number`. Разные валюты и нет `toAmount > 0` → `throw new Error('Укажите сумму зачисления')` до создания заявки. Разные валюты → строка описания `Сумма зачисления: ${toAmount} ${toRegister.currency}` (после «В кассу»). После `createPortalRequest` и до `submitRequestForApproval` — `setCashRegisterTransferTarget(created.id, { to_wallet_id: toRegister.wallet_id, ...(разные валюты ? { to_amount: toAmount } : {}) })`; ошибка → `CashRegisterTransferSubmitError(created.id, err)`.
- Формы: при разных валютах вместо предупреждения «уточните сумму зачисления в примечании» — обязательный `InputNumber` «Сумма зачисления (<валюта получателя>)», значение → `toAmount`.

- [ ] **Step 1: Тесты Vitest:** `cashRegisterTransfer.test.ts` — `calls target before submit` (порядок вызовов моков), `sends to_amount only for different currencies`, `rejects cross-currency without toAmount` (createPortalRequest не вызван), `target failure throws CashRegisterTransferSubmitError with requestId`. В `CashRegisterTransferButton.test.tsx` — `shows required credited amount for different currencies` (USD-касса → поле видно, без значения форма не отправляется) и мок `../lib/cashDeskApi`.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Commit** `feat(cash_desk): касса-получатель и сумма зачисления в форме перевода`

### Task 8: Фронтенд — страница настроек

**Files:**
- Create: `frontend_v2/src/ui/settings/CashDeskConfigPage.tsx`, `CashDeskConfigPage.test.tsx`
- Modify: `frontend_v2/src/routes/App.tsx` (route `settings/cash-desk-config` рядом с `settings/cash-withdrawal-config`), `frontend_v2/src/settings/settingsModules.tsx` (плитка «Касса: уведомления в Telegram», тот же доступ, что у «Снятия наличных»)

- Страница: `Switch` «Включено», `Select` «Кассовая группа» (`options.telegram_chats`, allowClear), подсказка «При оплате наличной заявки в группу уходит сообщение с остатками касс; перевод между кассами создаёт приход в кассе-получателе». Кнопка «Сохранить» → `saveCashDeskConfig`, `message.success('Сохранено')`.

- [ ] **Step 1: Тест:** `loads and saves config` (мок `../../lib/cashDeskApi`: get → чат выбран; переключить, сохранить → вызов с `{is_active: true, telegram_chat_id: 7}`).
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Commit** `feat(cash_desk): страница настроек «Касса»`

### Task 9: Спека, push, PR и список для n8n

- [ ] **Step 1:** Положить спеку в `docs/superpowers/specs/2026-11-06-cash-desk-notifications-design.md` и план в `docs/superpowers/plans/`, commit `docs: спека и план «Касса в портале»`.
- [ ] **Step 2:** `make push`; дождаться «Backend Tests» и «Vitest» зелёными; открыть PR в `main` (тело — что меняется, порядок включения, список n8n из спеки).
- [ ] **Step 3:** Через n8n API (`~/.config/n8n-api/api_key`, только GET) сверить, что узлы из спеки («HTTP Cash Revenue1», «Send Cash Notification1», «Send Cash Notification2»; neuron «Send a text message»; qulay «Send message and wait for response», «HTTP Request3», «Send a text message1») существуют, активны и стоят на нужных ветках; отдать пользователю итоговый список по тенантам плюс шаги: включить «Касса» в портале, пригласить бота портала в группу NEW, настроить «Снятие наличных» для Qulay, удалить узлы с паролем в Qulay.
