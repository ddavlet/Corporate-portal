# API для n8n (backend_v2)

Документ описывает **интеграционный API** (`apps/modules/n8n_integration/`) для **импорта/апдейта (upsert)** данных из n8n в Kolberg.

## Базовый URL и маршрутизация

- **Base path**: `"/api/<n8n_prefix>/"`.
- `n8n_prefix` берётся из env `N8N_INTEGRATION_URL_PATH` (нормализуется; по умолчанию `"n8n"`).
- Для совместимости API монтируется по **одному или двум** префиксам (см. `settings.N8N_INTEGRATION_MOUNT_PATHS`):
  - всегда `"/api/<N8N_INTEGRATION_URL_PATH>/"`,
  - и дополнительно `"/api/n8n/"`, если `N8N_INTEGRATION_URL_PATH != "n8n"`.

Рекомендуемый URL для клиентов: **`/api/n8n/`** (или ваш кастомный префикс).

## Tenant resolution (как выбирается тенант)

Для всех URL с n8n-префиксом tenant определяется **по subdomain из Host** (middleware `N8nIntegrationTenantMiddleware`):

- **Обязательно** передавать `Host` вида `<tenant_subdomain>.<BASE_DOMAIN>`
- Если subdomain не извлечён → **400** `{"detail": "Could not determine tenant from request Host."}`
- Если tenant не найден/не активен → **404** `{"detail": "Unknown tenant."}`

## Аутентификация и права доступа

Каждый запрос должен пройти **двойную** проверку:

1) **Интеграционный секрет** (общий для n8n):
- Заголовок: **`X-N8N-Integration-Token`**
- Значение должно совпасть с tenant-конфигом `n8n_integration_token` (если задан), иначе fallback на env `N8N_INTEGRATION_TOKEN`
- Если токен не сконфигурирован → **503**: `"N8N_INTEGRATION_TOKEN is not configured."`
- Если неверный → **401**: `"Invalid integration token."`

2) **JWT пользователя** (DRF SimpleJWT):
- Заголовок: **`Authorization: Bearer <access_jwt>`**
- Если JWT не передан/невалиден → **401**

3) **Роль внутри тенанта**:
- Дополнительно требуется permission `IsTenantAdmin`
- Если пользователь не админ данного tenant → **403**

## Tenant-level integration settings

Часть интеграционных параметров теперь настраивается tenant-admin через портал:

- `GET /api/tenant-integration-config/`
- `PUT /api/tenant-integration-config/`

Секреты хранятся зашифрованно и в ответе API маскируются.

## Общий контракт upsert

Все n8n-эндпоинты работают по одному принципу:

- Метод: **POST**
- Тип: **Upsert по `id`**
- Поле **`id` обязательно** и должно быть **integer**
  - нет `id` → **400** `{"id": ["This field is required."]}`
  - `id` не int → **400** `{"id": ["Must be an integer."]}`

Логика:
- Если объект с таким `id` уже есть **в этом tenant** → частичный update (**partial=True**) → **200**
- Если объекта нет:
  - если `id` уже занят в другом tenant → **400** `{"id": ["This ID already exists in another tenant."]}`
  - иначе create с заданным `id` → **201**

Системный пользователь:
- Для некоторых сущностей при create выставляется `created_by` в **system user `pk=1`**
- Если `User(pk=1)` отсутствует → **503** `{"detail":"System user (pk=1) is missing."}`

Ошибки валидации DRF:
- `serializer.is_valid(raise_exception=True)` → стандартные **400** с полями.

## Endpoints (n8n integration)

Ниже `<base>` = `/api/<n8n_prefix>/` (например `/api/n8n/`).

Важно: request-related интеграции из `n8n_integration` удалены. Эндпоинты
`<base>requests/`, `<base>approvals/`, `<base>approvals/confirm/`,
`<base>approvals/by-message-id/` больше не используются.
Telegram-согласования вынесены в модуль `apps.modules.telegram_approvals`:
- inbound webhook: `/api/telegram-approvals/webhook/`
- outbound dispatch: `https://<subdomain>.<base_domain>/n8n/telegram/dispatch`

**Уведомление о черновике автозаявки (без суммы в шаблоне):** backend шлёт POST на тот же dispatch URL с полем `action`, равным значению настройки `telegram_approvals_draft_notification_action` (по умолчанию логика в коде — **`send_draft_notification`**). В теле JSON помимо `message`, `parse_mode`, `chat_id` передаются `request_id`, **`draft_url`** (если задан env **`REQUESTS_PORTAL_PUBLIC_BASE_URL`**, иначе пустая строка), **`notification_kind`**: `draft_needs_amount`, **`inline_keyboard`**: `[]`. Ветка n8n должна отправлять обычное сообщение (без кнопок согласования), при желании добавить URL-кнопку с `draft_url`.

### Requests upsert + read

- **POST** `<base>requests/`
- **GET** `<base>requests/`
  - без параметров: вернуть список requests текущего tenant (сортировка по `submitted_at desc, id desc`)
  - с `?id=<int>`: вернуть конкретный request
  - `id` не integer → **400** `{"id": ["Must be an integer."]}`
  - request не найден в tenant → **404** `{"detail": "Not found."}`

Важные правила:
- `requester` должен быть **активным членом tenant** и иметь роль **`requester`**
- `vendor_ref` (если задан) должен принадлежать tenant и соответствовать `payment_type`
- **file_link special-case (импорт из n8n)**:
  - если приходит абсолютный `http(s)://...`:
    - на **создании** всегда скачивается в Django storage
    - на **обновлении** скачивается **только если** текущий `Request.file_link` пустой
  - для скачивания используется env **`N8N_TOKEN`** как `Authorization: Bearer <N8N_TOKEN>`
  - если `N8N_TOKEN` не настроен → **400** `{"file_link":"N8N_TOKEN is not configured."}`

Схема `POST <base>requests/`:

- `id`: required, `integer`
- `company_payer`: optional, `string`
- `category`: optional, `string`
- `vendor`: optional, `string`
- `vendor_ref`: optional, `integer | null`
- `title`: optional, `string`
- `description`: optional, `string`
- `amount`: optional, `decimal`
- `currency`: optional, `enum` (`UZS|USD|EUR|RUB`)
- `payment_type`: optional, `enum` (`Наличные|Перечисление|Пополнение|Платежная карта`)
- `urgency`: optional, `enum` (`Низко|Обычно|Срочно`)
- `requester`: optional, `integer` (user id)
- `payment_purpose`: optional, `string`
- `submitted_at`: optional, `datetime | null`
- `status`: optional, `enum` (`DRAFT|1|2|3|4|5|APPROVED|PAYED|REJECTED`)
- `payed_at`: optional, `integer | null`
- `expense_id`: optional, `string | null`
- `file_link`: optional, `string | null` (URL или storage path)
- `expense_year`: optional, `integer | null`
- `expense_month`: optional, `integer | null`
- `expense_day`: optional, `integer | null`
- `billing_date`: optional, `date`

Тело запроса для `POST <base>requests/` (пример):

```json
{
  "id": 1001,
  "company_payer": "ACME LLC",
  "category": "Операционные расходы",
  "vendor": "Поставщик 1",
  "vendor_ref": 42,
  "title": "Оплата услуг",
  "description": "Счет за март",
  "amount": "1500000.00",
  "currency": "UZS",
  "payment_type": "Перечисление",
  "urgency": "Обычно",
  "requester": 10,
  "payment_purpose": "Оплата по договору",
  "submitted_at": "2026-03-30T10:30:00Z",
  "status": "DRAFT",
  "expense_id": "INV-2026-03-001",
  "file_link": "https://example.com/file.pdf",
  "billing_date": "2026-03-31"
}
```

Для `GET <base>requests/` тело запроса **не используется**.

### Approvals upsert

- **POST** `<base>approvals/`

Схема `POST <base>approvals/`:

- `id`: required, `integer`
- `request`: required, `integer` (Request id)
- `approver_user`: optional, `integer | null`
- `approver_tg_id`: optional, `integer | null`
- `approver_tg_from_id`: optional, `integer | null`
- `message_id`: optional, `integer | null`
- `message_sent`: optional, `boolean`
- `step`: optional, `integer`
- `step_type`: optional, `enum` (`serial|payment`)
- `decision`: optional, `enum` (`pending|approved|rejected`)
- `comment`: optional, `string | null`
- `decided_at`: optional, `datetime | null`

Тело запроса (пример):

```json
{
  "id": 501,
  "request": 1001,
  "approver_user": 12,
  "approver_tg_id": 123456789,
  "approver_tg_from_id": 987654321,
  "message_id": 555,
  "message_sent": true,
  "step": 1,
  "step_type": "serial",
  "decision": "pending",
  "comment": "",
  "decided_at": null
}
```

### Approvals confirm (текущий шаг) + lookup по message_id

- **POST** `<base>approvals/confirm/`
- **GET** `<base>approvals/by-message-id/?message_id=<int>`

#### POST `<base>approvals/confirm/`

Назначение:
- подтверждает **конкретный pending approval** по `approval_id`;
- approver должен совпасть с назначением шага (по `approver_user_id` или `chat_id`/`from_id`);
- для Telegram-сценария рекомендуется передавать **`from_id`** и проверять подтверждение именно по нему
  (при наличии `chat_id` лучше передавать оба поля: `chat_id` + `from_id`);
- после подтверждения пересчитывается статус `Request`:
  - если pending-шаги закончились и нет rejected -> `APPROVED`;
  - если остались pending -> статус прогресса (`1..5`) по минимальному pending step;
  - если есть rejected -> `REJECTED`.

Тело запроса:
- `approval_id`: required, `integer`
- `request_id`: optional, `integer` (доп. проверка, что approval принадлежит этому request)
- `decision`: optional, `integer` (`-1|0|1` => `rejected|pending|approved`, default: `1`)
- `approver_user_id`: optional, `integer`
- `chat_id`: optional, `integer`
- `from_id`: optional, `integer`
- `comment`: optional, `string | null`
- `decided_at`: optional, `datetime` (если не передан, ставится текущее время сервера)

Правило идентификации approver:
- обязательно передать хотя бы один идентификатор: `approver_user_id` или `chat_id` или `from_id`;
- для Telegram подтверждений используйте `from_id` как основной идентификатор пользователя.

Пример:

```json
{
  "approval_id": 501,
  "decision": 1,
  "chat_id": 123456789,
  "from_id": 987654321,
  "comment": "approved from telegram"
}
```

Ответ `200` (сокращённый пример):

```json
{
  "message": "Решение по согласованию успешно сохранено.",
  "request": {
    "id": 1001,
    "status": "APPROVED"
  },
  "trigger_approval": {
    "id": 501,
    "step": 1,
    "decision": "approved"
  },
  "approvals": [
    {
      "id": 501,
      "step": 1,
      "decision": "approved"
    }
  ]
}
```

Ошибки:
- `400`:
  - `{"approval_id": ["This field is required and must be integer."]}`
  - `{"decision": ["Must be one of -1, 0, 1."]}`
  - `{"decided_at": ["Must be a valid datetime."]}`
  - `{"chat_id": ["Must be an integer."]}` / `{"from_id": ["Must be an integer."]}` / `{"approver_user_id": ["Must be an integer."]}`
- `403`: approver не назначен на текущий pending-шаг
- `404`: request не найден в tenant
- `409`: решение по согласованию уже принято

Формат ответа для endpoint confirm:
- endpoint всегда возвращает JSON с полем `message` (на русском),
  при `200` дополнительно возвращается контекст `request/trigger_approval/approvals`.

Webhook-уведомления по новым правилам:
- при изменении `Request.status` на `APPROVED` или `PAYED` backend отправляет
  `POST` на `<base>request/status/` с payload текущего подтверждения (`approval`);
- при вызове `approvals/confirm` backend отправляет `POST` на `<base>approval/status/`
  с payload текущего подтверждения даже если решение не изменилось (например, ошибка `409`);
- в обоих webhook payload содержит поля `approval` (подтверждение) и `request` (заявка)
  и `status_change_attempted` (для `approval/status` всегда `true`).

#### GET `<base>approvals/by-message-id/?message_id=<int>`

Назначение:
- поиск `Approval` по `message_id` в пределах tenant;
- возврат полного контекста: `request`, `trigger_approval`, `approvals[]`.

Параметры:
- `message_id`: required, `integer`

Пример:

`GET /api/n8n/approvals/by-message-id/?message_id=555`

Ошибки:
- `400`:
  - `{"message_id": ["This query param is required."]}`
  - `{"message_id": ["Must be an integer."]}`
- `404`: `Approval` с таким `message_id` не найден

### Vendors upsert

- **POST** `<base>vendors/`

Правила:
- Для `kind=transfer` поле `inn` обязательно и уникально в рамках `(tenant, kind=transfer)`.

Схема `POST <base>vendors/`:

- `id`: required, `integer`
- `kind`: required, `enum` (`cash|transfer`)
- `name`: required, `string`
- `inn`: optional, `string | null` (**required если `kind=transfer`**)
- `account_number`: optional, `string | null`

Тело запроса (пример):

```json
{
  "id": 42,
  "kind": "cash",
  "name": "Imported vendor",
  "inn": null,
  "account_number": null
}
```

### Cash expenses upsert

- **POST** `<base>cash/expenses/`

Примечание:
- Для надёжности **передавайте `external_id` явно** (вместе с `id`), а также `expense_at`.

Схема `POST <base>cash/expenses/`:

- `id`: required, `integer`
- `external_id`: required, `string` (рекомендуется передавать всегда)
- `confirmed`: optional, `boolean`
- `title`: optional, `string`
- `amount`: optional, `decimal`
- `currency`: optional, `enum` (`UZS|USD|EUR|RUB`)
- `expense_at`: required, `datetime`
- `note`: optional, `string`
- `payload`: optional, `object | array | string | number | boolean | null` (JSONField)
- `vendor`: optional, `integer | null` (Vendor id, kind=`cash`)

Тело запроса (пример):

```json
{
  "id": 7001,
  "external_id": "CASH-7001",
  "confirmed": true,
  "title": "Кассовый расход",
  "amount": "250000.00",
  "currency": "UZS",
  "expense_at": "2026-03-30T09:00:00Z",
  "note": "Оплата хоз. расходов",
  "payload": {},
  "vendor": 42
}
```

### Cash revenues upsert

- **POST** `<base>cash/revenues/`

Схема `POST <base>cash/revenues/`:

- `id`: required, `integer`
- `title`: optional, `string`
- `amount`: optional, `decimal`
- `currency`: optional, `enum` (`UZS|USD|EUR|RUB`)
- `revenue_date`: optional, `date`
- `category`: optional, `string`
- `received_from`: optional, `string`
- `payment_method`: optional, `string`
- `reference_no`: optional, `string`
- `status`: optional, `string`
- `tags`: optional, `string`
- `note`: optional, `string`
- `payload`: optional, `object | array | string | number | boolean | null` (JSONField)

Тело запроса (пример):

```json
{
  "id": 7101,
  "title": "Кассовое поступление",
  "amount": "1000000.00",
  "currency": "UZS",
  "revenue_date": "2026-03-30",
  "category": "Возврат",
  "received_from": "Контрагент A",
  "payment_method": "cash",
  "reference_no": "RV-100",
  "status": "confirmed",
  "tags": "n8n,import",
  "note": "Комментарий",
  "payload": {}
}
```

### Bank expenses upsert

- **POST** `<base>bank/expenses/`

Схема `POST <base>bank/expenses/`:

- `id`: required, `integer`
- `row_no`: optional, `integer | null`
- `doc_date`: required, `date` (принимается гибкий формат дат `TashkentFlexibleDateField`)
- `process_date`: required, `date` (принимается гибкий формат дат `TashkentFlexibleDateField`)
- `expense_year`: optional, `integer | null` (если не передан, выводится из `doc_date`)
- `expense_month`: optional, `integer | null` (если не передан, выводится из `doc_date`)
- `expense_day`: optional, `integer | null` (если не передан, выводится из `doc_date`)
- `doc_no`: optional, `string`
- `account_name`: optional, `string`
- `inn`: optional, `string`
- `account_no`: optional, `string`
- `mfo`: optional, `string`
- `debit_turnover`: optional, `decimal`
- `payment_purpose`: optional, `string`
- `vendor`: optional, `integer | null` (Vendor id, kind=`transfer`)

Тело запроса (пример):

```json
{
  "id": 8001,
  "row_no": 1,
  "doc_date": "2026-03-30",
  "process_date": "2026-03-30",
  "doc_no": "BEXP-001",
  "account_name": "Поставщик 2",
  "inn": "123456789",
  "account_no": "20208000123456789012",
  "mfo": "01001",
  "debit_turnover": "3500000.00",
  "payment_purpose": "Оплата поставки",
  "vendor": 55
}
```

### Bank revenues upsert

- **POST** `<base>bank/revenues/`

Особенность:
- `BankRevenue` привязан к тенанту через `tenant_subdomain` (из Host subdomain).

Схема `POST <base>bank/revenues/`:

- `id`: required, `integer`
- `row_no`: optional, `integer | null`
- `doc_date`: required, `date` (принимается гибкий формат дат `TashkentFlexibleDateField`)
- `process_date`: required, `date` (принимается гибкий формат дат `TashkentFlexibleDateField`)
- `doc_no`: optional, `string`
- `account_name`: optional, `string`
- `inn`: optional, `string`
- `account_no`: optional, `string`
- `mfo`: optional, `string`
- `kredit_turnover`: optional, `decimal`
- `payment_purpose`: optional, `string`

Тело запроса (пример):

```json
{
  "id": 8101,
  "row_no": 1,
  "doc_date": "2026-03-30",
  "process_date": "2026-03-30",
  "doc_no": "BREV-001",
  "account_name": "Плательщик 1",
  "inn": "987654321",
  "account_no": "20208000987654321000",
  "mfo": "01002",
  "kredit_turnover": "4200000.00",
  "payment_purpose": "Поступление оплаты"
}
```

### Corporate card expenses upsert

- **POST** `<base>corporate-card/expenses/`

Схема `POST <base>corporate-card/expenses/`:

- `id`: required, `integer`
- `title`: optional, `string`
- `amount`: optional, `decimal`
- `currency`: optional, `enum` (`UZS|USD|EUR|RUB`)
- `expense_at`: optional, `datetime`
- `note`: optional, `string`
- `payload`: optional, `object | array | string | number | boolean | null` (JSONField)

Тело запроса (пример):

```json
{
  "id": 9001,
  "title": "Расход по карте",
  "amount": "450000.00",
  "currency": "UZS",
  "expense_at": "2026-03-30T08:15:00Z",
  "note": "Командировочные",
  "payload": {}
}
```

### Corporate card revenues upsert

- **POST** `<base>corporate-card/revenues/`

Нормализации:
- если пришёл `total_sum` и нет `amount` → `amount = total_sum`
- если пришёл `comment` и нет `note` → `note = comment`
- если `revenue_at` задан, а `revenue_date` нет → `revenue_date = revenue_at.date()`

Схема `POST <base>corporate-card/revenues/`:

- `id`: required, `integer`
- `external_id`: optional, `string`
- `revenue_date`: optional, `date`
- `confirmed`: optional, `boolean`
- `direction`: optional, `string`
- `organization`: optional, `string`
- `unit`: optional, `string`
- `employee`: optional, `string`
- `cash_type`: optional, `string`
- `operation`: optional, `string`
- `account`: optional, `string`
- `counterparty`: optional, `string`
- `total_sum`: optional, `decimal`
- `comment`: optional, `string`
- `source_year`: optional, `integer | null` (обычно вычисляется сервером)
- `title`: optional, `string`
- `amount`: optional, `decimal`
- `currency`: optional, `enum` (`UZS|USD|EUR|RUB`)
- `revenue_at`: optional, `datetime | null`
- `note`: optional, `string`
- `payload`: optional, `object | array | string | number | boolean | null` (JSONField)
- `bank_expense_id`: optional, `integer | null`

Тело запроса (пример):

```json
{
  "id": 9101,
  "external_id": "CARD-9101",
  "revenue_date": "2026-03-30",
  "confirmed": true,
  "direction": "in",
  "organization": "ACME LLC",
  "unit": "Finance",
  "employee": "Ivan Ivanov",
  "cash_type": "card",
  "operation": "topup",
  "account": "8600123412341234",
  "counterparty": "Bank",
  "total_sum": "500000.00",
  "comment": "Пополнение карты",
  "currency": "UZS",
  "payload": {},
  "bank_expense_id": null
}
```

### Notes upsert

- **POST** `<base>notes/`

Правила:
- `recipient_user` должен быть активным членом tenant и иметь `telegram_chat_id`
- `target_type/target_id` валидируются на существование объекта в tenant и доступ к модулю.

Схема `POST <base>notes/`:

- `id`: required, `integer`
- `recipient_user`: required, `integer` (tenant user id, активный, с `telegram_chat_id`)
- `target_type`: required, `enum` (поддерживаемые значения модели Note: `request|cash|bank`)
- `target_id`: required, `integer`
- `message`: required, `string`
- `delivery_status`: optional, `string`
- `delivery_error`: optional, `string`
- `sent_at`: optional, `datetime | null`

Тело запроса (пример):

```json
{
  "id": 10001,
  "recipient_user": 12,
  "target_type": "request",
  "target_id": 1001,
  "message": "Новая задача на согласование",
  "delivery_status": "pending",
  "delivery_error": "",
  "sent_at": null
}
```

### Payroll lines upsert

- **POST** `<base>payroll/lines/`

Правила:
- `doc_id` связывает линию с `PayrollDocument` (документ создаётся автоматически при необходимости).

Схема `POST <base>payroll/lines/`:

- `id`: required, `integer`
- `doc_id`: required, `string`
- `line_no`: required, `integer`
- `employee`: required, `string`
- `item`: required, `string`
- `description`: optional, `string`
- `sum`: required, `decimal`
- `days_plan`: optional, `integer | null`
- `days_fact`: optional, `integer | null`
- `period_start`: optional, `date | null`
- `period_end`: optional, `date | null`
- `approval`: optional, `boolean | null`

Тело запроса (пример):

```json
{
  "id": 11001,
  "doc_id": "DOC-PAY-2026-03",
  "line_no": 1,
  "employee": "Ivan",
  "item": "Зарплата",
  "description": "",
  "sum": "1000.00",
  "days_plan": 22,
  "days_fact": 20,
  "period_start": "2026-03-01",
  "period_end": "2026-03-31",
  "approval": false
}
```

## Пример запроса (curl)

```bash
curl -X POST "https://acme.example.com/api/n8n/vendors/" \
  -H "Host: acme.example.com" \
  -H "Content-Type: application/json" \
  -H "X-N8N-Integration-Token: <N8N_INTEGRATION_TOKEN>" \
  -H "Authorization: Bearer <ACCESS_JWT_ТЕНАНТ_АДМИНА>" \
  -d '{"id":42,"kind":"cash","name":"Imported vendor"}'
```

## Коды ответов

- **200**: обновили существующую запись (upsert update)
- **201**: создали новую запись (upsert create)
- **400**: ошибки полей / конфликт id между tenant’ами / tenant по Host не определён
- **401**: нет/неверный `X-N8N-Integration-Token` или JWT
- **403**: JWT есть, но пользователь не tenant admin, либо approver не назначен на текущий шаг confirm
- **404**: tenant не найден по subdomain, request/approval не найдены (в lookup/confirm)
- **503**: интеграция/системный пользователь не сконфигурированы


