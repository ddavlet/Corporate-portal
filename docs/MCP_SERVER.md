# Kolberg MCP Server

Reference documentation for the **Kolberg Data Server** — a [Model Context Protocol](https://modelcontextprotocol.io) server that lets AI assistants (Claude, ChatGPT, n8n agents) work with **one company's** Kolberg data: requests, finances, reports, payroll, investments, budgets, tasks and directories.

Source: [`backend_v2/apps/mcp_server/`](../backend_v2/apps/mcp_server/) · Design: [`docs/superpowers/specs/2026-09-30-tenant-mcp-design.md`](superpowers/specs/2026-09-30-tenant-mcp-design.md)

---

## 1. Overview

- **One connector = one company.** The server lives on every tenant host: `https://<subdomain>.kolberg.uz/mcp` (e.g. `https://lemonfit.kolberg.uz/mcp`). The tenant comes from the host; no tool takes `tenant_id`.
- **39 tools.** Everything is read-only except the tasks tools (`create_task`, `update_task_status`, `add_task_comment`, `edit_task`, `delete_task`).
- **Filtered per user.** `list_tools` returns only the tools allowed by the company's enabled modules and the user's roles (§5). Calling a hidden tool behaves exactly like calling a nonexistent one (`Unknown tool: <name>`).
- **Transport:** streamable HTTP (stateless). **Framework:** `MCPServer` from the `mcp` Python SDK 2.x, running inside the Django project (same ORM, same tenant rules as the web API).

The former shared endpoint `https://api.kolberg.uz/mcp` and the stdio mode (`run_mcp_server`, `KOLBERG_JWT_TOKEN`) were removed.

---

## 2. Connecting a client

**Claude** (claude.ai / Desktop): Settings → Connectors → *Add custom connector* → URL `https://<subdomain>.kolberg.uz/mcp`.

**ChatGPT**: Settings → Security and login → enable *Developer mode*; then Connectors → *Create* → URL `https://<subdomain>.kolberg.uz/mcp`, Authentication: **OAuth**.

The client discovers OAuth automatically and opens the company's login page (`https://<subdomain>.kolberg.uz/mcp/login/`). The user enters their portal username and the one-time code sent by **that company's** Telegram bot. Requirements: the company has MCP enabled (§3) and the user is an active member of it.

A user who works in several companies adds one connector per company.

---

## 3. Switches

| Switch | Where | Effect |
|---|---|---|
| `MCP_HTTP_ENABLED` | `docker-compose.yml` (`backend_v2` env) | Global on/off. Off → `/mcp` and discovery return 404 on every host. |
| `Tenant.mcp_enabled` | Django admin / DB | Per company. Off (or tenant inactive / unknown subdomain) → 404 on that host. |
| `MCP_ALLOWED_ORIGINS` | env, default `https://claude.ai,https://claude.com,https://chatgpt.com` | Browser `Origin`s allowed to call `/mcp`. Requests without `Origin` (server-to-server) are allowed; any other `Origin` → 403. |

---

## 4. Authentication

### 4.1 OAuth (people)

Discovery is served per host by `config/asgi.py`:

- `/.well-known/oauth-protected-resource[/mcp]` → `resource` = `authorization_servers` = `https://<subdomain>.kolberg.uz/mcp`
- `/.well-known/oauth-authorization-server[/mcp]` → issuer `https://<subdomain>.kolberg.uz/mcp`, endpoints `/mcp/authorize`, `/mcp/token`, `/mcp/register`; DCR, PKCE `S256`, `authorization_code` + `refresh_token`.
- Any 401 carries `WWW-Authenticate: Bearer … resource_metadata="https://<subdomain>.kolberg.uz/.well-known/oauth-protected-resource"`.

Flow and checks:

1. `authorize` — if the client sends an RFC 8707 `resource` that is not this host's `/mcp`, the request fails (`invalid_request`). The tenant id is put into the signed login parameters.
2. `/mcp/login/` (Django, `McpLoginView`) — the signed tenant must equal the host tenant; the user must be an active member; the OTP is sent/verified with `tenant=<this company>`. The authorization code stores the tenant.
3. `token` — a code issued for another tenant is rejected. Issued JWTs carry the claim **`mcp_tenant_id`**.
4. Every MCP request — the access token's `mcp_tenant_id` must equal the host tenant, otherwise 401. Refresh tokens are exchanged only on their own host.

Token isolation: tokens without `mcp_tenant_id` (portal tokens, tokens from the old shared endpoint) are not accepted by MCP, and the portal API (`PortalJWTAuthentication`, also the n8n integration auth) **rejects** tokens that have `mcp_tenant_id`. A leaked connector token cannot be used against the portal API.

Lifetimes: access `MCP_ACCESS_TOKEN_MINUTES` (default 60), refresh `MCP_REFRESH_TOKEN_DAYS` (default 7).

### 4.2 Service keys (n8n and other bots)

Header `X-Service-Key: <key>` on `https://<subdomain>.kolberg.uz/mcp`. The key (model `McpServiceCredential`, managed in Django admin; only its hash is stored) works **only on hosts of the tenants it is bound to**. The middleware mints a short-lived token for the key's synthetic admin user with `svc=True` and `mcp_tenant_id=<host tenant>`. An unknown, inactive or unbound key gets the same `401 {"error": "Invalid or inactive service key"}`. A service key sees every tool enabled for the company (synthetic admin).

---

## 5. Tool visibility

A tool is listed and callable when its rule allows the user in this company. Module rules also require the module to be enabled for the company (`TenantModuleConfig`) and the user's role to grant it in `ROLE_MODULE_ACCESS` (`apps/tenants/permissions.py`).

| Rule | Tools |
|---|---|
| always (members) | `get_current_tenant`, `get_my_role`, `list_my_modules` |
| module `requests` | `list_requests`, `get_request`, `list_request_categories` |
| module `cash` | `list_cash_expenses`, `list_cash_revenues` |
| module `bank` | `list_bank_expenses`, `list_bank_revenues` |
| module `corporate_card` | `list_card_expenses`, `list_card_revenues` |
| module `reports` | `get_pnl_report`, `get_cashflow_report` |
| module `payroll` | `list_payroll_documents`, `get_payroll_document` |
| module `investments` | `get_investment_form_config`, `list_invest_companies`, `list_invest_returns`, `list_project_investments`, `list_invest_payout_schedule` |
| module `budgets` | `list_budgets`, `get_budget`, `list_budget_spend_requests` |
| module `tasks` | `list_my_tasks`, `get_task`, `update_task_status`, `add_task_comment`, `edit_task`, `delete_task`, `list_assignee_candidates` |
| module `tasks` + admin/director | `create_task` |
| module `vendors` | `list_vendors` |
| module `wallets` | `list_wallets` |
| admin or director | `list_active_users`, `get_tenant_info`, `list_module_configs` |
| admin | `list_user_roles`, `list_memberships` |

The map lives in the `@tool(access=...)` decorators in `server.py` and is pinned by `McpToolAccessRegistryTests`. Tool functions in `tools/*.py` still check access themselves (`require_module_access` etc.) as a second line of defence.

---

## 6. Error handling

All tools return `{"error": "..."}` (or `[{"error": "..."}]` for list tools) instead of raising. Messages are in English, e.g. `Access denied: your role does not allow access to module 'cash', or the module is disabled for this tenant`, `Task 5 not found or not accessible.`, `Request 99 not found in this tenant`.

---

## 7. Tools reference

No tool takes `tenant_id` — every tool works on the connector's company. Date filters use **`YYYY-MM-DD`** only. `limit` is clamped to its valid range (out-of-range values are silently corrected, not rejected). Who can see each tool: §5.

### 7.0 Context

- `get_current_tenant()` — the connector's company: `id`, `name`, `subdomain`.
- `get_my_role()` — the current user's roles in the company.
- `list_my_modules()` — modules that are enabled **and** accessible to the current user.

### 7.1 Requests (заявки) — module `requests`

#### `list_requests`
Lists payment requests with optional filters.

| Parameter | Type | Notes |
|-----------|------|-------|
| `status` | str | `DRAFT`, `1`–`5`, `APPROVED`, `PAYED`, `REJECTED` (deleted requests are never returned) |
| `currency` | str | `UZS`, `USD`, `EUR`, `RUB` |
| `payment_type` | str | `Наличные`, `Перечисление`, `Пополнение`, `Платежная карта`, `Начисление ЗП` |
| `urgency` | str | `Низко`, `Обычно`, `Срочно` |
| `date_from` / `date_to` | str | Filters on `created_at` (date part) |
| `limit` | int | Default 50, max 200 |

Returns a list of request objects (see the field table in §8). Ordered newest-first by `created_at`.

#### `get_request`
Returns one request by `request_id`, including its full approval chain.

The result is a request object plus an `approvals` list, each entry: `id`, `step`, `step_type`, `decision`, `approver_user_id`, `comment`, `decided_at`.

#### `list_request_categories`
Returns all **active** request categories for the tenant: `id`, `name`, `is_active`, `created_at`.

### 7.2 Cash desk (касса) — module `cash`

#### `list_cash_expenses`
Cash outflows. Filters: `date_from`/`date_to` (on `expense_at`), `currency`, `limit` (50/200).
Fields: `id`, `external_id`, `title`, `amount`, `currency`, `expense_at`, `expense_year`, `expense_month`, `expense_day`, `note`, `confirmed`, `vendor_id`, `wallet_id`, `created_at`.

#### `list_cash_revenues`
Cash inflows. Filters: `date_from`/`date_to` (on `revenue_at`), `limit` (50/200).
Fields: `id`, `external_id`, `total_sum` (the revenue amount), `currency`, `revenue_at`, `source_year`, `confirmed`, `created_at`.

### 7.3 Bank — module `bank`

#### `list_bank_expenses`
Bank statement **debit** rows. Filters: `date_from`/`date_to` (on `doc_date`), `limit` (50/200).
Fields: `id`, `doc_no`, `doc_date`, `process_date`, `debit_turnover` (debited amount), `payment_purpose`, `expense_year`, `expense_month`, `expense_day`, `vendor_id`, `wallet_id`, `created_at`.

#### `list_bank_revenues`
Bank statement **credit** rows. Filters: `date_from`/`date_to` (on `doc_date`), `limit` (50/200).
Fields: `id`, `doc_no`, `doc_date`, `process_date`, `kredit_turnover` (credited amount), `payment_purpose`, `account_name`, `inn`, `account_no`, `mfo`, `wallet_id`, `created_at`.
> `account_name`, `inn`, `account_no`, `mfo` describe the **counterparty** on that statement line — not the tenant's own bank account.

### 7.4 Corporate card — module `corporate_card`

#### `list_card_expenses` / `list_card_revenues`
Corporate-card outflows / inflows (top-ups, refunds). Filters: `date_from`/`date_to` (on `expense_at`), `limit` (50/200).
Fields: `id`, `title`, `amount`, `currency`, `expense_at`, `note`, `wallet_id`, `created_at`.

### 7.5 Payroll (начисления ЗП) — module `payroll`

#### `list_payroll_documents`
Payroll documents with totals and workflow state (same fields as the portal list).
Params: `status` (`draft`/`accepted`/`closed`/`cancelled`), `kind` (`salary`/`advance`/`bonus`), `period_from`/`period_to` (on `period_month`), `limit` (50/200).
Fields: `id`, `doc_id`, `label`, `status`, `kind`, `period_month`, `source`, `payout_mode`, `created_at`, `total_sum`, `paid_total`, `lines_count`, `has_request`, `has_paid_request`, `matched_request_id`.

#### `get_payroll_document`
One payroll document by `document_id`, with **all employee lines**.
Returns the list fields plus `remaining_total`, `current_request`, `closed_underpaid_at`, `close_comment`, and:
- `lines[]`: `id`, `line_no`, `employee`, `employee_id`, `item`, `description`, `sum`, `days_plan`, `days_fact`, `period_start`, `period_end`, `approval`;
- `employees[]`: `employee_id`, `full_name`, `accrued`, `paid`, `remaining`;
- `payouts[]`: `cash_expense_id`, `date`, `amount`, `wallet_id`.

### 7.6 Directories (справочники)

#### `list_vendors` — module `vendors`
Vendor directory.
Filters: `kind` (`cash` or `transfer`), `name_search` (case-insensitive substring), `limit` (default **100**, max **500**).
Fields: `id`, `kind`, `name`, `inn`, `account_number`, `created_at`, `created_by_id`.

#### `list_wallets` — module `wallets`
All wallets of the company (no limit).
Fields: `id`, `wallet_type` (`cash` / `bank` / `corporate_card`), `currency`, `opening_balance`, `opening_balance_at`, `is_visible_in_cash_section`, `cash_register_id`, `bank_account_id`, `corporate_card_account_id`.
> Exactly one of the three `*_id` anchor columns is set per wallet, matching `wallet_type`.

### 7.8 Tenant configuration

#### `get_tenant_info`
Public tenant metadata.
Fields: `id`, `name`, `subdomain`, `is_active`, `telegram_otp_enabled`, `telegram_bot_username`.

#### `list_module_configs`
Every module's enable/disable flag for the company.
Fields per row: `id`, `module_key`, `is_enabled`.

#### `list_user_roles`
All user→role assignments in the tenant.
Fields per row: `id`, `user_id`, `role`.

#### `list_memberships`
All tenant memberships.
Fields per row: `id`, `user_id`, `is_active`.

### 7.9 Reports — module `reports`

#### `get_pnl_report` / `get_cashflow_report`
Full PnL / Cashflow report built from the company's saved rules (`pnl_config` for PnL, `cashflow_config` for Cashflow).

| Parameter | Type | Notes |
|-----------|------|-------|
| `date_from` / `date_to` | str | `YYYY-MM-DD`. Narrows the report window on top of the report's `start_month`. Optional. |
| `aggregate` | bool | Default `false`. When `true`, each bucket collapses to `{total, count, by_month, by_category}` instead of line items. |

> ⚠ **Unfiltered, non-aggregated calls return every line since `start_month`** — for a tenant with a long history this can be thousands of rows and a very large response. Pass `date_from`/`date_to` and/or `aggregate=true` unless individual line items are actually needed.

Response shape (`aggregate=false`): `{ "revenue", "operational_expenses", "other_expenses", "invest_returns" }`, each a list of `{ id, date, amount, category, purpose, description }`, plus `metadata` and `report_settings`.
Response shape (`aggregate=true`): same four keys, each `{ total, count, by_month: {"YYYY-MM": amount}, by_category: {category: amount} }`, plus `"aggregated": true`.

`get_pnl_report` expenses use `billing_date` (accrual, amortization-aware); `get_cashflow_report` expenses use the actual cash payment date (no amortization).

### 7.10 Investments — module `investments`

- `get_investment_form_config()` — whether company filters apply and which `return_type` values are allowed.
- `list_invest_companies(name_search, is_active, limit)` — legal entities / projects.
- `list_invest_returns(date_from, date_to, return_type, recipient, company_id, confirmed, limit)` — payouts to investors (PnL `invest_returns`).
- `list_project_investments(date_from, date_to, company_id, confirmed, limit)` — capital invested into projects.
- `list_invest_payout_schedule(date_from, date_to, company_id, is_paid, limit)` — planned payout calendar (plan vs fact).

### 7.11 Budgets — module `budgets`

- `list_budgets(year, period, category_name, is_active, limit)` — limits vs spend (`spent_amount`, `remaining`, `utilization_pct`); spend = APPROVED + PAYED requests by `billing_date`.
- `get_budget(budget_id, year, period)` — one budget with utilization.
- `list_budget_spend_requests(budget_id, year, period, limit)` — requests counted toward the budget.

### 7.12 Tasks — module `tasks` (the only write tools)

- `list_my_tasks(status, limit)` / `get_task(task_id)` — admins and directors see all tasks, others only their own.
- `create_task(assignee_id, title, description)` — admin/director only.
- `update_task_status(task_id, new_status)` — `new → in_progress | done`, `in_progress → new | done`.
- `add_task_comment(task_id, body)`, `edit_task(task_id, title, description, assignee_id)`, `delete_task(task_id)` — creator, admin or director (comment: assignee too).
- `list_assignee_candidates()` — valid `assignee_id` values.

### 7.13 Users

- `list_active_users()` — active members with roles (`id`, `full_name`, `username`, `roles`); admin or director.

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

1. Call `get_current_tenant()` to confirm which company the connector works on.
2. Use only the tools you are given — they are already filtered to what this user may do. `list_my_modules()` explains what is enabled.
3. For expenses use requests (`list_requests`), not raw cash/bank/card feeds, unless the user explicitly asks for raw transactions.
4. Always check each result for an `error` key before using it.
5. For "spend in month X" questions, filter on the **accrual period** (`billing_date` / `expense_year`+`expense_month`); for "cash movement in month X", filter on operational dates (`expense_at`, `doc_date`, `created_at`).

---

## 10. Routing & file layout

- Traefik router `django-v2-tenant-mcp` (`docker-compose.yml`): tenant hosts × (`/mcp`, `/mcp/*`, `/.well-known/oauth-*`) → `django-v2`.
- `config/asgi.py` `_tenant_mcp`: resolves the tenant from `Host` (404 if unknown/disabled), checks `Origin` (403), binds the tenant contextvar, then serves discovery JSON, sends `/mcp/login/` to Django, or `/mcp/*` to the MCP app.

```
backend_v2/apps/mcp_server/
├── server.py            TenantScopedMCPServer + the 39 @tool(access=...) wrappers
├── access.py            Access rules + visible_tools() (list_tools filtering)
├── django_tools.py      @tool decorator: hides tenant_id, sync_to_async, TOOL_ACCESS
├── tenant_context.py    tenant from Host, contextvar, Origin check
├── routing.py           path predicates used by config/asgi.py
├── auth.py              tenant-bound JWT decode + tenant/role/module checks
├── services.py          service-key provisioning and verification
├── http/
│   ├── app.py           MCP ASGI app (SDK auth wiring)
│   ├── middleware.py    401 → per-host resource_metadata
│   └── service_key.py   X-Service-Key → tenant-bound token
├── oauth/
│   ├── provider.py      KolbergOAuthProvider (tenant-bound codes and tokens)
│   ├── views.py         /mcp/login/ OTP login
│   ├── metadata.py      per-host discovery documents
│   └── tokens.py        JWT pair with mcp_tenant_id
└── tools/               query logic per domain (requests, finance, directories,
                         investments, budgets, tasks, tenant_config, integrations)
```

**Design split:** `server.py` defines the tool surface, access rules and the uniform error envelope; `tools/` modules hold the query logic and call into `auth.py`. Django models are imported lazily inside functions.
