# Kolberg MCP Server

Reference documentation for the **Kolberg Data Server** — a [Model Context Protocol](https://modelcontextprotocol.io) server that exposes **read-only** access to a single Kolberg tenant's data so AI assistants can query requests, finances, directories, and tenant configuration.

Source: [`backend_v2/apps/mcp_server/`](../backend_v2/apps/mcp_server/)

---

## 1. Overview

Kolberg is a multi-tenant corporate finance platform: payment **requests** (заявки) with multi-step approval, financial modules (cash desk, bank, corporate card, payroll), and reference directories (vendors, wallets).

The MCP server lets an AI client (Claude Desktop, IDE extensions, custom agents) read that data through a fixed set of **17 tools**. It does **not** write, update, or delete anything — it is a query surface only.

- **Transport:** stdio (the server is spawned as a subprocess by the MCP client).
- **Framework:** `FastMCP` from the `mcp` Python SDK (`mcp>=1.0.0,<2.0.0`).
- **Runtime:** runs inside the Django project — it imports the real ORM models, so every query goes through the same database and the same multi-tenant rules as the web API.
- **Scope:** one running server instance = one user identity (one JWT) acting across the tenants that user belongs to.

---

## 2. Status — what is working

| Area | Status |
|------|--------|
| 17 tools across 8 data domains | ✅ Implemented |
| Authentication via `KOLBERG_JWT_TOKEN` env var | ✅ Working |
| Role + module-config access enforcement | ✅ Working (reuses `apps.tenants.permissions`) |
| Tenant scoping on every query | ✅ Working |
| Date-filter validation (`YYYY-MM-DD`) | ✅ Working |
| Uniform error envelope | ✅ Working |
| Secrets redaction (integration tokens never exposed) | ✅ Working |
| Unit tests (`json_safe`, `validate_date`) | ✅ 12/12 passing |
| Live tool-invocation verification | ✅ All 17 tools verified |

**Not implemented (by design):** any write/create/update/delete operation; the `investments`, `notes`, `contracts`, `clients_debt`, `budgets`, `reports`, `feedback` modules have no tools exposed yet.

---

## 3. Starting the server

The JWT token is supplied through the `KOLBERG_JWT_TOKEN` environment variable. It is read **once at startup** and is never passed as a tool-call parameter — this keeps it out of MCP logs and AI conversation history.

**Via the Django management command (recommended):**

```bash
KOLBERG_JWT_TOKEN=<access_token> python manage.py run_mcp_server
```

**Directly as a module (bootstraps Django itself):**

```bash
KOLBERG_JWT_TOKEN=<access_token> python -m apps.mcp_server.server
```

Both must run from the `backend_v2/` directory so `config.settings` and the database configuration resolve. If `KOLBERG_JWT_TOKEN` is missing, the management command exits immediately with a clear error.

Obtain the access token from the portal auth endpoint `POST /api/auth/token/`.

### MCP client configuration example

```json
{
  "mcpServers": {
    "kolberg": {
      "command": "python",
      "args": ["manage.py", "run_mcp_server"],
      "cwd": "/path/to/backend_v2",
      "env": { "KOLBERG_JWT_TOKEN": "<access_token>" }
    }
  }
}
```

---

## 4. Authentication & security model

Every tool call runs through the same checks ([`auth.py`](../backend_v2/apps/mcp_server/auth.py)):

1. **Token presence** — `KOLBERG_JWT_TOKEN` must be set.
2. **Token validity** — decoded with `rest_framework_simplejwt.AccessToken`; expired or malformed tokens fail. The `user_id` claim identifies the caller.
3. **User & tenant resolution** — the user must exist; the `tenant_id` argument must point to an **active** tenant; the user must hold an **active** `TenantMembership` in that tenant.
4. **Authorization** — one of three checks depending on the tool:
   - **Module access** — the module must be enabled for the tenant (`TenantModuleConfig.is_enabled`) **and** the user's role must grant that module.
   - **Admin** — the user must hold the `admin` role.
   - **Admin or director** — the user must hold `admin` or `director`.

Any failure raises `PermissionError`, which the tool converts into an error result.

**Security properties:**

- **Read-only.** No tool mutates data.
- **Tenant-isolated.** Every query is filtered by `tenant=<resolved tenant>`. Cross-tenant access is impossible — passing another tenant's `tenant_id` fails the membership check.
- **Secrets redacted.** `get_integration_config` never returns encrypted values — only booleans indicating whether each secret is set.
- **Token off-channel.** The JWT lives in the process environment, never in tool arguments or results.

---

## 5. Roles & module access matrix

A module tool succeeds only when **both** conditions hold: the module is enabled for the tenant, and the caller's role appears in the row below ([`apps/tenants/permissions.py`](../backend_v2/apps/tenants/permissions.py)).

| Module key | admin | director | approver | requester | cashier | accountant | investor |
|------------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `requests` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `vendors`  | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `wallets`  | ✅ | ✅ | — | — | ✅ | ✅ | — |
| `cash`     | ✅ | ✅ | — | — | ✅ | — | — |
| `bank`     | ✅ | ✅ | — | — | — | ✅ | — |
| `corporate_card` | ✅ | ✅ | — | — | ✅ | ✅ | — |
| `payroll`  | ✅ | ✅ | — | — | — | ✅ | — |

Admin-only / admin-or-director tools do **not** depend on `TenantModuleConfig`:

| Tool | Required role |
|------|---------------|
| `get_integration_config`, `list_user_roles`, `list_memberships` | `admin` |
| `get_tenant_info`, `list_module_configs` | `admin` or `director` |

---

## 6. Error handling

Tools never raise to the client. On failure they return a uniform envelope:

- **Object-returning tools** → `{"error": "message"}`
- **List-returning tools** → `[{"error": "message"}]`

**Always check for an `error` key before using a result.** Common messages:

| Cause | Example message |
|-------|-----------------|
| Token not set | `KOLBERG_JWT_TOKEN environment variable is not set.` |
| Token invalid/expired | `Invalid or expired token: ...` |
| Wrong / inactive tenant | `Tenant 5 not found or inactive` |
| Not a member | `User is not an active member of this tenant` |
| Role / module disabled | `Access denied: your role does not allow access to module 'cash', or the module is disabled for this tenant` |
| Admin required | `Admin role required for this operation` |
| Bad date filter | `'date_from' must be a valid date in YYYY-MM-DD format, got: '15/03/2024'` |
| Record not found | `Request 99 not found in this tenant` |

---

## 7. Tools reference

All 17 tools take `tenant_id` (integer) as the first argument. Date filters use **`YYYY-MM-DD`** only. `limit` is clamped to its valid range (out-of-range values are silently corrected, not rejected).

### 7.1 Requests (заявки) — module `requests`

#### `list_requests`
Lists payment requests with optional filters. **Roles:** admin, director, approver, requester, accountant, cashier.

| Parameter | Type | Notes |
|-----------|------|-------|
| `status` | str | `DRAFT`, `1`–`5`, `APPROVED`, `PAYED`, `REJECTED` |
| `currency` | str | `UZS`, `USD`, `EUR`, `RUB` |
| `payment_type` | str | `Наличные`, `Перечисление`, `Пополнение`, `Платежная карта`, `Начисление ЗП` |
| `urgency` | str | `Низко`, `Обычно`, `Срочно` |
| `date_from` / `date_to` | str | Filters on `created_at` (date part) |
| `limit` | int | Default 50, max 200 |

Returns a list of request objects (see the field table in §8). Ordered newest-first by `created_at`.

#### `get_request`
Returns one request by `request_id`, including its full approval chain. **Roles:** same as above.

The result is a request object plus an `approvals` list, each entry: `id`, `step`, `step_type`, `decision`, `approver_user_id`, `comment`, `decided_at`.

#### `list_request_categories`
Returns all **active** request categories for the tenant: `id`, `name`, `is_active`, `created_at`. **Roles:** same as above.

### 7.2 Cash desk (касса) — module `cash`

#### `list_cash_expenses`
Cash outflows. **Roles:** admin, director, cashier. Filters: `date_from`/`date_to` (on `expense_at`), `currency`, `limit` (50/200).
Fields: `id`, `external_id`, `title`, `amount`, `currency`, `expense_at`, `expense_year`, `expense_month`, `expense_day`, `note`, `confirmed`, `vendor_id`, `wallet_id`, `created_at`.

#### `list_cash_revenues`
Cash inflows. **Roles:** admin, director, cashier. Filters: `date_from`/`date_to` (on `revenue_at`), `limit` (50/200).
Fields: `id`, `external_id`, `total_sum` (the revenue amount), `currency`, `revenue_at`, `source_year`, `confirmed`, `created_at`.

### 7.3 Bank — module `bank`

#### `list_bank_expenses`
Bank statement **debit** rows. **Roles:** admin, director, accountant. Filters: `date_from`/`date_to` (on `doc_date`), `limit` (50/200).
Fields: `id`, `doc_no`, `doc_date`, `process_date`, `debit_turnover` (debited amount), `payment_purpose`, `expense_year`, `expense_month`, `expense_day`, `vendor_id`, `wallet_id`, `created_at`.

#### `list_bank_revenues`
Bank statement **credit** rows. **Roles:** admin, director, accountant. Filters: `date_from`/`date_to` (on `doc_date`), `limit` (50/200).
Fields: `id`, `doc_no`, `doc_date`, `process_date`, `kredit_turnover` (credited amount), `payment_purpose`, `account_name`, `inn`, `account_no`, `mfo`, `wallet_id`, `created_at`.
> `account_name`, `inn`, `account_no`, `mfo` describe the **counterparty** on that statement line — not the tenant's own bank account.

### 7.4 Corporate card — module `corporate_card`

#### `list_card_expenses`
Corporate-card outflows. **Roles:** admin, director, accountant, cashier. Filters: `date_from`/`date_to` (on `expense_at`), `limit` (50/200).
Fields: `id`, `title`, `amount`, `currency`, `expense_at`, `note`, `wallet_id`, `created_at`.

#### `list_card_revenues`
Corporate-card inflows. **Roles:** admin, director, accountant, cashier. Filters: `date_from`/`date_to` (on `revenue_at`), `limit` (50/200).
Fields: `id`, `external_id`, `title`, `amount`, `currency`, `revenue_at`, `note`, `confirmed`, `wallet_id`, `created_at`.

### 7.5 Payroll (начисления ЗП) — module `payroll`

#### `list_payroll_documents`
Payroll documents (headers). **Roles:** admin, director, accountant. Param: `limit` (50/200).
Fields: `id`, `doc_id` (external document identifier), `created_at`.

#### `get_payroll_document`
One payroll document by `document_id`, with **all employee lines**. **Roles:** same as above.
Returns `id`, `doc_id`, `created_at`, and `lines[]`. Each line: `id`, `line_no`, `employee`, `item`, `description`, `sum`, `days_plan`, `days_fact`, `period_start`, `period_end`, `approval`.

### 7.6 Directories (справочники)

#### `list_vendors` — module `vendors`
Vendor directory. **Roles:** admin, director, approver, requester, cashier, accountant.
Filters: `kind` (`cash` or `transfer`), `name_search` (case-insensitive substring), `limit` (default **100**, max **500**).
Fields: `id`, `kind`, `name`, `inn`, `account_number`, `created_at`, `created_by_id`.

#### `list_wallets` — module `wallets`
All wallets for the tenant (no limit). **Roles:** admin, director, accountant, cashier.
Fields: `id`, `wallet_type` (`cash` / `bank` / `corporate_card`), `currency`, `opening_balance`, `opening_balance_at`, `is_visible_in_cash_section`, `cash_register_id`, `bank_account_id`, `corporate_card_account_id`.
> Exactly one of the three `*_id` anchor columns is set per wallet, matching `wallet_type`.

### 7.7 Integrations

#### `get_integration_config`
Integration metadata for the tenant. **Roles:** admin only.
Returns `tenant_id`, `configured` (bool). When configured, also: `updated_at`, `updated_by_id`, `telegram_oidc_client_id`, `telegram_oidc_redirect_uri`, `messaging_gateway_feedback_recipient_id`, `messaging_gateway_feedback_action`, and the secret-presence booleans `n8n_integration_token_set`, `requests_file_gateway_token_set`, `telegram_oidc_client_secret_set`.
> Encrypted secret **values** are never returned — only whether each secret is set.

### 7.8 Tenant configuration

#### `get_tenant_info`
Public tenant metadata. **Roles:** admin or director.
Fields: `id`, `name`, `subdomain`, `is_active`, `telegram_otp_enabled`, `telegram_bot_username`.

#### `list_module_configs`
Every module's enable/disable flag for the tenant. **Roles:** admin or director.
Fields per row: `id`, `module_key`, `is_enabled`. Use this first to learn which module tools will work.

#### `list_user_roles`
All user→role assignments in the tenant. **Roles:** admin only.
Fields per row: `id`, `user_id`, `role`.

#### `list_memberships`
All tenant memberships. **Roles:** admin only.
Fields per row: `id`, `user_id`, `is_active`.

---

## 8. Field glossary & domain notes

### Request object fields

`get_request` and `list_requests` return the same 29-field shape:

| Field | Meaning |
|-------|---------|
| `id` | Request primary key. |
| `title` | **Auto-set to the tenant's name** on every save — it is not a user-entered subject line. |
| `status` | Lifecycle stage — see *Status codes* below. |
| `amount` / `currency` | Requested payment amount and its currency. |
| `payment_type` | How it will be paid — see *Payment types* below. |
| `urgency` | `Низко` (low) / `Обычно` (normal) / `Срочно` (urgent). |
| `category` | Free-text expense category. |
| `vendor` | Free-text vendor name as typed on the request. |
| `vendor_ref_id` | FK to a `Vendor` directory entry, when the request is linked to one (else `null`). |
| `contract_ref_id` | FK to a `Contract`, when linked (else `null`). |
| `company_payer` | The legal entity that pays. |
| `payment_purpose` | Stated purpose of the payment. |
| `description` | Free-text description. |
| `billing_date` | **Accrual date** — see *Billing date & accrual period* below. |
| `created_at` | When the request record was created. |
| `submitted_at` | When the request was submitted into the approval flow. |
| `payed_at` | Integer timestamp set when the request is paid; `null` until then. |
| `created_by_id` | User who created the request. |
| `requester_id` | User on whose behalf the request is made (may differ from creator; nullable). |
| `expense_id` | Business/transport key carried from external payloads (e.g. n8n). |
| `expense_ref_id` | Primary key of the actual expense document this request became — see *Expense reference* below. |
| `expense_ref_target` | Which table `expense_ref_id` points at: `cash`, `bank`, `card`, or `payroll`. |
| `expense_year` / `expense_month` / `expense_day` | The accrual period expressed as integers (see below). |
| `file_link` | Link to an attached file, if any. |
| `amortization_months` | Number of months the cost is spread across (default 1 = not amortized). |
| `amortization_start_date` | Month the amortization schedule begins (nullable). |

### Billing date & accrual period

`billing_date` answers **"which period is this payment *for*?"** — not when it was created or paid.

A payment is often made in a different calendar month from the one it economically belongs to. Example: a tenant pays **June's** office rent at the end of **May**, one month early. The request is *created* in May, but its `billing_date` falls in **June**, because June is the period the rent covers.

This is why request and expense rows carry both:

- **Operational dates** — `created_at`, `submitted_at`, `payed_at`, `expense_at`, `doc_date` → *when the action happened*.
- **Accrual period** — `billing_date` and the `expense_year` / `expense_month` / `expense_day` triplet → *which period the money belongs to*.

When reporting "spend for month X", filter by the **accrual period**, not by `created_at`. When reporting "cash that moved in month X", filter by the operational date.

`amortization_months` extends the same idea: a 12-month insurance premium paid once can be amortized — `amortization_months = 12` starting at `amortization_start_date` spreads that one payment across 12 accrual periods.

### Status codes (`Request.status`)

| Value | Meaning |
|-------|---------|
| `DRAFT` | Created but not yet submitted for approval. |
| `1`–`5` | In progress — the number is the current approval step the request sits at. |
| `APPROVED` | All approval steps passed; awaiting payment. |
| `PAYED` | Payment has been made. |
| `REJECTED` | Rejected at some approval step. |

### Payment types (`Request.payment_type`)

| Value | English |
|-------|---------|
| `Наличные` | Cash |
| `Перечисление` | Bank transfer |
| `Пополнение` | Top-up / replenishment |
| `Платежная карта` | Payment card |
| `Начисление ЗП` | Payroll accrual (links to `PayrollDocument.doc_id` via `expense_id`) |

### Approval chain

`get_request` includes `approvals[]`, ordered by `step`. Each approval has:

- `step_type` — `serial` (a normal sequential approval), `payment` (the payment-execution step), or `notification` (informational only).
- `decision` — `pending`, `approved`, `rejected`, or `canceled`.
- `approver_user_id`, `comment`, `decided_at`.

The same request may show multiple rows for the same `step` when an approval was re-sent (a new resend batch) — this is expected, not duplication.

### Expense reference

When a request results in a real expense document, `expense_ref_id` + `expense_ref_target` link to it. `expense_ref_target` tells you **which tool** to use to fetch the document, because primary keys are not unique across modules:

| `expense_ref_target` | Lives in | Fetch via |
|----------------------|----------|-----------|
| `cash` | Cash expenses | `list_cash_expenses` |
| `bank` | Bank expenses | `list_bank_expenses` |
| `card` | Corporate-card expenses | `list_card_expenses` |
| `payroll` | Payroll documents | `get_payroll_document` |

### `confirmed` flag (cash & corporate-card rows)

`confirmed` distinguishes a finalized financial record from a provisional/imported one. Treat unconfirmed rows as not-yet-reconciled.

### Wallets

A `Wallet` is the money container for a channel. Its `wallet_type` is `cash`, `bank`, or `corporate_card`, and exactly one anchor FK is populated to match:

- `cash` → `cash_register_id` (a cash register; multiple per currency allowed).
- `bank` → `bank_account_id` (one synthetic bank anchor per tenant).
- `corporate_card` → `corporate_card_account_id` (one per currency).

`opening_balance` / `opening_balance_at` define the starting balance; running balances are computed from the expense/revenue rows, not stored on the wallet.

---

## 9. Recommended workflow for an AI client

1. **Ask the user for their `tenant_id`** (the numeric ID of their organization).
2. **Call `list_module_configs(tenant_id)`** to see which modules are enabled. Only call module tools whose module is enabled — disabled ones always return a permission error.
3. **Query the data domains** the user asked about.
4. **If access is denied**, and the caller is an admin, call `list_user_roles(tenant_id)` to inspect role assignments and explain the gap.
5. **Always check each result for an `error` key** before using it.
6. For "spend in month X" questions, filter on the **accrual period** (`billing_date` / `expense_year`+`expense_month`); for "cash movement in month X", filter on operational dates (`expense_at`, `doc_date`, `created_at`).

---

## 10. File layout

```
backend_v2/apps/mcp_server/
├── server.py            FastMCP instance + the 17 @mcp.tool() wrappers
├── auth.py              JWT decode + tenant/role/module authorization
├── utils.py             json_safe() ORM-to-JSON, validate_date()
├── tests.py             Unit tests for utils
├── admin.py             (placeholder — no models)
├── management/commands/
│   └── run_mcp_server.py   Django command to launch the server
└── tools/
    ├── requests.py      list_requests, get_request, list_request_categories
    ├── finance.py       cash / bank / card / payroll tools
    ├── directories.py   list_vendors, list_wallets
    ├── integrations.py  get_integration_config
    └── tenant_config.py get_tenant_info, list_module_configs,
                         list_user_roles, list_memberships
```

**Design split:** `server.py` defines the MCP tool surface and the uniform error envelope; the `tools/` modules hold the query logic and call into `auth.py`. Django ORM models are imported lazily inside each function so the module graph stays light and import-order safe.
