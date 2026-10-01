# Тенантный MCP: отдельный адрес на каждую компанию

- **Дата:** 2026-09-30
- **Статус:** дизайн согласован в чате, ожидает ревью спеки
- **Модуль:** `backend_v2/apps/mcp_server/` (см. `docs/MCP_SERVER.md`)
- **Заменяет:** общий MCP на `https://api.kolberg.uz/mcp` (удаляется в этом же релизе)

## Зачем

Сейчас доменный MCP — один адрес `api.kolberg.uz/mcp` на все тенанты. Каждый из 39 инструментов принимает `tenant_id`, модель сама выбирает компанию через `list_my_tenants`. Проблемы:

- модель может ответить по другой компании (перепутать `tenant_id`);
- один токен даёт доступ ко всем тенантам пользователя — коннектор, расшаренный в компании, видит лишнее;
- модель видит все 39 инструментов, включая те, что вернут `Access denied`;
- MCP-токены — обычные access-токены simplejwt: портал принимает их, а MCP принимает токены портала.

Общим MCP никто не пользуется (последний OAuth-вход 2026-05-31, сервисный ключ — один раз 2026-08-24), поэтому общий переделывается, а не дополняется вторым сервером.

## Цель и критерий успеха

Для каждой компании — свой коннектор `https://<поддомен>.kolberg.uz/mcp` в Claude / ChatGPT. Пользователь входит по OTP на поддомене своей компании (как в портал).

Успех: коннектор `https://lemonfit.kolberg.uz/mcp` добавлен, вход по OTP прошёл; модель видит только инструменты, разрешённые включёнными модулями тенанта и ролью пользователя; ни один инструмент не принимает `tenant_id`; данные другой компании получить невозможно ни токеном, ни сервисным ключом.

## Решения (зафиксированы)

| Вопрос | Решение |
|---|---|
| Где адрес | Поддомен тенанта: `https://<subdomain>.kolberg.uz/mcp` |
| Общий `api.kolberg.uz/mcp` | Удаляется в этом релизе |
| Способы входа | OAuth (люди) + `X-Service-Key` (n8n). Ручной JWT (stdio, токены портала) удаляется |
| Фильтрация инструментов | Да: `list_tools` по включённым модулям и роли; скрытый инструмент при вызове = `Unknown tool` |
| Сервер | Один `MCPServer` на все поддомены, тенант из `Host` через contextvar |

## 1. Маршрутизация

### Traefik (`docker-compose.yml`, сервис `backend_v2`)

Новый роутер на существующем правиле хостов тенантов:

```
traefik.http.routers.django-v2-tenant-mcp.rule=(${TRAEFIK_BACKEND_V2_HOST_RULE}) && (Path(`/mcp`) || PathPrefix(`/mcp/`) || PathPrefix(`/.well-known/oauth-`))
traefik.http.routers.django-v2-tenant-mcp.priority=1300
(+ entrypoints/tls/certresolver/service как у django-v2-api)
```

Роутер `django-v2-mcp` (`Host(${MCP_HOST})`) удаляется. Новых переменных `.env` не нужно.

### `config/asgi.py`

HTTP-запрос при `MCP_HTTP_ENABLED`:

1. Путь `/mcp`, `/mcp/*` или `/.well-known/oauth-*` → тенантная ветка; иначе → Django (как сейчас).
2. Тенант резолвится из `Host` той же функцией, что в `TenantSubdomainMiddleware` (`_get_subdomain` + `BASE_DOMAIN`). Не найден / `is_active=False` / `mcp_enabled=False` → **404** (факт наличия MCP не раскрывается).
3. Заголовок `Origin` присутствует и не входит в `MCP_ALLOWED_ORIGINS` ∪ `https://<хост>` → **403**. Запрос без `Origin` (сервер-сервер, n8n) пропускается. (Встроенная защита SDK от DNS rebinding поддерживает только точные хосты, поэтому хост и Origin проверяет наш роутер; в SDK `enable_dns_rebinding_protection=False`.)
4. Тенант кладётся в contextvar `current_mcp_tenant` (id, subdomain, host) на время запроса.
5. Диспетчеризация:
   - `/.well-known/oauth-protected-resource[/mcp]`, `/.well-known/oauth-authorization-server[/mcp]` → JSON-метаданные для хоста (раздел 2);
   - `/mcp/login/` → Django-вью входа тенанта (раздел 2);
   - `/mcp`, `/mcp/*` → ASGI-приложение MCP (префикс `/mcp` срезается, как сейчас).

Lifespan проксируется в единственное MCP-приложение (как сейчас). Ветка `api.kolberg.uz` удаляется.

### Выключатели

`MCP_HTTP_ENABLED` (глобально) и `Tenant.mcp_enabled` (на компанию). Новых флагов нет.

## 2. OAuth и привязка токена к тенанту

Все адреса вычисляются из хоста запроса: `base = https://<subdomain>.<BASE_DOMAIN>/mcp`.

### Обнаружение

- `/.well-known/oauth-protected-resource[/mcp]` → `{"resource": base, "authorization_servers": [base], "scopes_supported": ["mcp"], "bearer_methods_supported": ["header"]}`
- `/.well-known/oauth-authorization-server[/mcp]` → `issuer = base`, `authorization_endpoint = base/authorize`, `token_endpoint = base/token`, `registration_endpoint = base/register`, остальное как сейчас (`code`, `authorization_code`+`refresh_token`, PKCE `S256`, `none`/`client_secret_*`).
- Любой 401 от MCP-приложения получает `WWW-Authenticate: Bearer … resource_metadata="https://<хост>/.well-known/oauth-protected-resource"` — новая host-aware версия `with_mcp_resource_metadata`.

`issuer_url` в `AuthSettings` SDK статичен и используется только для внутреннего маршрута метаданных под `/mcp/.well-known/...`; клиенты читают корневые метаданные, которые отдаём мы.

### Поток

1. **DCR** — существующая таблица `OAuthClient`, общая для всех тенантов.
2. **`authorize`** (`KolbergOAuthProvider.authorize`): тенант из contextvar. Если клиент передал RFC 8707 `resource` и он ≠ `base` этого хоста → `AuthorizeError(error="invalid_request")`, редиректа на вход нет. В подписанные параметры добавляется `tenant_id`; редирект на `base/login/?t=…`.
3. **Вход** `/mcp/login/` (новая вью на основе существующей OTP-вью): тенант из подписанных параметров должен совпадать с тенантом хоста; OTP отправляется и проверяется с `tenant=<этот тенант>` (`send_otp`/`verify_otp` уже принимают `tenant`, код придёт через бота компании); после OTP проверяется активное `TenantMembership` → иначе ошибка «Нет доступа к этой компании». Создаётся `OAuthAuthorizationCode` с `tenant`.
4. **Обмен кода** (`exchange_authorization_code`): `code.tenant_id` должен совпадать с тенантом хоста, иначе `invalid_grant`. Пара JWT получает claim `mcp_tenant_id`.
5. **Refresh** (`load_refresh_token` / `exchange_refresh_token`): claim `mcp_tenant_id` refresh-токена должен совпадать с тенантом хоста; новая пара несёт тот же claim.

### Проверка токена (каждый запрос)

`load_access_token`: JWT валиден **и** `mcp_tenant_id == тенант хоста` → иначе `None` (401). Токен без claim (токен портала, старые токены `api.kolberg.uz`) не принимается.

### Портал не принимает MCP-токены

Подкласс `JWTAuthentication` в новом файле `apps/accounts/authentication.py` отклоняет access-токены с claim `mcp_tenant_id`; подключается в `REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]` вместо базового. Токены портала не затронуты.

### Модель

`OAuthAuthorizationCode.tenant` — `ForeignKey(Tenant, null=True, on_delete=CASCADE)`. Миграция пишется вручную (как принято для веток), без удаления данных.

## 3. Инструменты и фильтрация

### Декларация доступа

Декоратор `tool` в `server.py` принимает `access`:

```python
@tool(access=Access.module("payroll"))
@tool(access=Access.module("tasks", admin_or_director=True))
@tool(access=Access.admin_or_director())
@tool(access=Access.admin())
@tool(access=Access.always())
```

`Access.allows(user, tenant, roles, enabled_modules)` — чистая функция над заранее загруженными ролями и включёнными модулями. Для модуля — та же логика, что `has_effective_module_access` (модуль включён у тенанта **и** роль в `ROLE_MODULE_ACCESS`).

### Карта доступа (39 инструментов)

| Access | Инструменты |
|---|---|
| `always` | `get_current_tenant`, `get_my_role`, `list_my_modules` |
| `module("requests")` | `list_requests`, `get_request`, `list_request_categories` |
| `module("cash")` | `list_cash_expenses`, `list_cash_revenues` |
| `module("bank")` | `list_bank_expenses`, `list_bank_revenues` |
| `module("corporate_card")` | `list_card_expenses`, `list_card_revenues` |
| `module("reports")` | `get_pnl_report`, `get_cashflow_report` |
| `module("payroll")` | `list_payroll_documents`, `get_payroll_document` |
| `module("investments")` | `get_investment_form_config`, `list_invest_companies`, `list_invest_returns`, `list_project_investments`, `list_invest_payout_schedule` |
| `module("budgets")` | `list_budgets`, `get_budget`, `list_budget_spend_requests` |
| `module("tasks")` | `list_my_tasks`, `get_task`, `update_task_status`, `add_task_comment`, `edit_task`, `delete_task`, `list_assignee_candidates` |
| `module("tasks", admin_or_director=True)` | `create_task` |
| `module("vendors")` | `list_vendors` |
| `module("wallets")` | `list_wallets` |
| `admin_or_director` | `list_active_users`, `get_tenant_info`, `list_module_configs` |
| `admin` | `list_user_roles`, `list_memberships` |

### Обёртки

- `tenant_id` удаляется из сигнатур всех инструментов; обёртка берёт `current_mcp_tenant().id` и передаёт в `tools/*.py` (функции в `tools/*.py` не меняются, их `require_module_access` остаётся вторым рубежом).
- `list_my_tenants` → `get_current_tenant` (id, name, subdomain).
- Из описаний удаляются «(get from list_my_tenants)», аргумент `tenant_id` и строки `Required roles` (модель видит только доступное; дублирование прав в тексте уже расходилось с кодом).
- Инструкции сервера переписываются под одну компанию: без шага выбора тенанта и без матрицы ролей; правило про источник правды для расходов сохраняется.

### Фильтрация

Подкласс `MCPServer` переопределяет:

- `list_tools()` — пользователь (из токена) и тенант (из contextvar); одним запросом роли пользователя в тенанте, одним — включённые модули; возвращаются инструменты, для которых `access.allows(...)`.
- `call_tool(name, …)` — если инструмент недоступен → `ToolError("Unknown tool: <name>")`, текст идентичен ответу на несуществующий инструмент.

Сервисный ключ = synthetic admin → видит всё включённое у тенанта.

## 4. Сервисные ключи и удаление старого

### Сервисные ключи

Host-aware версия middleware `X-Service-Key`: ключ найден, активен и `tenant ∈ credential.tenants` → выпускается короткий access-токен synthetic-пользователя с `svc=True` и `mcp_tenant_id=<тенант хоста>`; иначе **401** с единым сообщением (не раскрывает, почему). Модель `McpServiceCredential`, админка, выдача ключей не меняются.

### Удаляется

| Что | Где |
|---|---|
| Хост `api.kolberg.uz` | роутер Traefik `django-v2-mcp`, ветка в `asgi.py`, `is_mcp_host`/`mcp_hostname` в `routing.py` |
| Статические адреса | `MCP_HOST`, `MCP_BASE_URL`, `MCP_RESOURCE_URL`, `MCP_OAUTH_LOGIN_URL` в `settings.py` и `.env.example`; `api.kolberg.uz` из `DJANGO_ALLOWED_HOSTS` в `.env.example` |
| Старая страница входа | маршрут `/oauth/login/` (заменён на `/mcp/login/`) |
| stdio / ручной JWT | команда `run_mcp_server`, `server.run()`, чтение `KOLBERG_JWT_TOKEN` в `auth.py` |

### Не удаляется (данные)

Записи `OAuthClient`, `OAuthAuthorizationCode`, `McpServiceCredential` и synthetic-пользователи остаются в БД.

### Документация

`docs/MCP_SERVER.md` переписывается: адреса, подключение в Claude/ChatGPT, сервисные ключи, фильтрация, выключатели.

## 5. Тесты и выкатка

### Тесты (`apps/mcp_server/tests.py`)

- **Маршрутизация:** хост тенанта с `mcp_enabled` → MCP; неизвестный поддомен / неактивный / `mcp_enabled=False` → 404; `api.kolberg.uz/mcp` не обслуживается MCP; чужой `Origin` → 403.
- **Обнаружение:** метаданные и `WWW-Authenticate` указывают на хост запроса.
- **OAuth:** `authorize` с чужим `resource` → ошибка; вход без членства → отказ; код тенанта A на хосте B → `invalid_grant`; refresh тенанта A на хосте B → отказ.
- **Токены:** токен A на хосте B → 401; токен портала в MCP → 401; MCP-токен в API портала → 401; обычный токен портала в API портала → 200.
- **Сервисные ключи:** ключ привязан к тенанту → работает; не привязан → 401 с тем же текстом, что для неверного ключа.
- **Фильтрация:** наборы `list_tools` для requester / cashier / investor / admin; выключенный модуль скрывает свои инструменты; вызов скрытого → `Unknown tool`.
- **Обёртки:** тенант берётся из хоста; ни в одной схеме инструмента нет `tenant_id`.
- **Согласованность:** `Access` каждого модульного инструмента совпадает с модулем, который проверяет его функция в `tools/*.py` (замена теста `Required roles` из #322).

### Выкатка

1. **Предварительно — отдельный PR `fix/deploy-migrate-race`:** после `up -d --force-recreate backend_v2` скрипт ждёт (с таймаутом), пока контейнер пройдёт стартовый `migrate` (`showmigrations --plan` без `[ ]` или готовность gunicorn), и только потом выполняет `exec migrate` (иначе новая миграция `AddField` снова уронит деплой посередине).
2. PR `dev/tenant-mcp` → CI (`Backend Tests`) → мерж → `make deploy` (метки Traefik применятся при пересоздании `django_v2`).
3. `.env` на сервере менять не обязательно; `MCP_*` и `api.kolberg.uz` в `DJANGO_ALLOWED_HOSTS` можно убрать вручную позже.
4. Проверка: `curl https://lemonfit.kolberg.uz/.well-known/oauth-protected-resource`; подключение коннектора в Claude; `curl https://api.kolberg.uz/mcp/` больше не отвечает MCP.

## Вне рамок

- Новые модули в MCP (`clients_debt`, `contracts`, `notes`, `feedback`).
- Запись вне модуля задач.
- CIMD для ChatGPT (DCR достаточно).
- Удаление данных старых OAuth-клиентов.
- Вопросы по нескольким компаниям через один коннектор (подключается несколько коннекторов).
