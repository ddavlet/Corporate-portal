# MCP-сервер: сервисная авторизация по заголовку (tenant-scoped)

- **Date:** 2026-08-24 (revised after codebase audit — see "Revision note")
- **Status:** approved for implementation
- **Target:** `backend_v2/apps/mcp_server/` (см. `docs/MCP_SERVER.md`) — сейчас "parked" (`MCP_HTTP_ENABLED=false`)
- **Clients:** сервисные интеграции (n8n, другие бэкенды, AI-агенты) + люди через Cursor / Claude Desktop / Claude.ai web

## Revision note

Первая версия этой спеки предполагала, что HTTP-транспорт и OAuth-обвес для user-режима нужно строить с нуля (по образцу `kolberg-mcp/mcp_ud_report`), а сервисный режим — как отдельный `ServiceAuthContext`, который тулы должны научиться понимать.

Аудит реального кода `apps/mcp_server` показал, что это не так:

1. **HTTP + OAuth уже полностью реализованы и закоммичены** — `oauth/provider.py` (`KolbergOAuthProvider`), БД-модели `OAuthClient`/`OAuthAuthorizationCode`, `/oauth/login/` через OTP, per-request JWT через contextvar. Просто выключено флагом `MCP_HTTP_ENABLED=false`. Эта часть — **не задача этого плана**, только её включение на проде (шаг rollout).
2. **`user` в `require_module_access()`/`require_admin_access()`/`require_admin_or_director()` используется не только для проверки допуска, но и внутри бизнес-логики самих тулов** — например `list_requests` определяет видимость кросс-тенантных записей через `TenantUserRole.objects.filter(user=user, role=ADMIN)`, `list_tasks`/`get_task_detail` через `resolve_scope_for_user(user, tenant)` (admin/director видят все таски тенанта, остальные — только свои). Отдельный "безпользовательский" `ServiceAuthContext` сломал бы эти тулы.

Решение: сервисный ключ выдаётся не "как отдельный тип авторизации", а разрешается в **настоящего synthetic-пользователя** с ролью admin в разрешённых тенантах. Это делает нулевыми правки в `auth.py`-точках входа и во всех файлах `tools/*.py`.

## Context

`apps/mcp_server` — read-only MCP-сервер с бизнес-тулами Kolberg (заявки, касса, банк, корп. карта, ЗП, задачи, инвестиции, бюджеты, справочники). Multi-tenant платформа: один тенант = одна компания-клиент. Модель `Tenant` уже имеет флаг `mcp_enabled` (по умолчанию `False`) — MCP работает только для тенантов, где он явно включён.

Сегодня единственный способ авторизации — настоящий JWT человека (через `KOLBERG_JWT_TOKEN` env var в stdio-режиме, либо через `Authorization: Bearer <JWT>` — включая JWT, выданный уже готовым OAuth-обвесом для claude.ai). Внутри каждого тула `tenant_id` передаётся явным аргументом и проверяется по `TenantMembership` + ролевой/модульной матрице (`apps/tenants/permissions.py`).

Этой модели не хватает: **сервисным интеграциям** (n8n-воркфлоу, другой бэкенд, AI-агент не от имени конкретного человека) не нужен OTP-логин человека — им нужен долгоживущий ключ, который открывает доступ строго к заранее определённому набору тенантов, без интерактивного флоу.

## Goals

- Ввести **сервисный режим** авторизации: HTTP-заголовок `X-Service-Key`, ключ хранится в БД (`McpServiceCredential`), привязан к множеству тенантов через обычный M2M.
- Каждому ключу соответствует один synthetic `User` ("service-user") с `TenantMembership(is_active=True)` + `TenantUserRole(role=ADMIN)` в каждом из привязанных тенантов — это даёт доступ ко **всем** тулам в этих тенантах, включая admin-only (`get_integration_config`, `list_user_roles`, `list_memberships`), без единой правки в `tools/*.py`.
- Полная изоляция: сервисный ключ не может ни прочитать данные тенанта вне своего списка, ни узнать через различие в сообщениях об ошибке, что такой тенант вообще существует.
- Ключ работает поверх уже существующего HTTP/OAuth транспорта (переиспользует `mcp_jwt_pair_for_user`-паттерн из `oauth/tokens.py`), без новых транспортных слоёв.

## Non-goals

- Изменение HTTP/OAuth-обвеса для user-режима — он уже реализован (`oauth/`), трогаем только по минимуму (см. Components §3).
- Изменение ролевой/модульной матрицы для человеческих пользователей.
- Write-доступ любого рода — сервер остаётся read-only.
- TTL / автоматическая ротация сервисных ключей по расписанию — отзыв только через `is_active=False`.
- Полный аудит-лог каждого вызова — только `last_used_at` на credential.
- Изменение поведения для тенантов, где `mcp_enabled=False` или конкретный модуль выключен — сервисный ключ подчиняется тем же тенантным тумблерам, что и обычный admin (это ограничение самого тенанта, а не роли вызывающего).

## Architecture

```
                    X-Service-Key: <key>
                            │
                            ▼
         ┌─ apps/mcp_server/http/service_key.py ──────────────┐
         │  lookup McpServiceCredential by key_prefix          │
         │  invalid/inactive → 401, НЕ идёт дальше (fail-closed)│
         │  valid → mint AccessToken.for_user(service_user)     │
         │          claim "svc"=True, переписывает заголовок    │
         │          Authorization: Bearer <token> в scope       │
         └──────────────────────┬───────────────────────────────┘
                                 ▼
              with_mcp_resource_metadata(...)   ← без изменений
                                 ▼
              FastMCP → KolbergOAuthProvider.load_access_token   ← без изменений
                                 ▼
              apps/mcp_server/auth.py: require_module_access(...) и т.д.
                 (существующая логика; для service-user это ролевая
                  проверка admin — просто проходит, т.к. роль настоящая)
                                 ▼
                          tools/*.py           ← БЕЗ ИЗМЕНЕНИЙ
```

Если `X-Service-Key` отсутствует — запрос идёт как раньше, через обычный `Authorization: Bearer <JWT>` (ручной или из OAuth-обмена).

## Components

### 1. `McpServiceCredential` (новая модель, `apps/mcp_server/models.py`)

| Поле | Назначение |
|---|---|
| `key_prefix` | Индексированный короткий префикс ключа — O(1) lookup без сканирования хешей |
| `key_hash` | `django.contrib.auth.hashers.make_password` от секретной части ключа |
| `name` | Человекочитаемое имя интеграции |
| `service_user` | `OneToOneField(User)` — synthetic-пользователь, создаётся автоматически, `set_unusable_password()` |
| `tenants` | `ManyToManyField(Tenant)` — источник правды для допуска |
| `is_active` | Отзыв без передеплоя |
| `created_at`, `last_used_at` | Аудит по минимуму |

Формат выдаваемого ключа: `svc_<key_prefix>_<секрет>` (аналог GitHub PAT), секрет ~32 байта url-safe, хешируется. Ключ показывается **один раз** в момент создания (в Django admin через `messages.WARNING`), дальше не восстановим — только перевыпуск.

### 2. `apps/mcp_server/services.py` (новый файл)

- `provision_service_credential(name: str, tenant_ids: list[int]) -> tuple[McpServiceCredential, str]` — создаёт `service_user`, ключ (возвращает raw-ключ, хранит только хеш), создаёт `McpServiceCredential`, привязывает `tenants`, вызывает `sync_tenant_access`.
- `sync_tenant_access(credential: McpServiceCredential) -> None` — идемпотентно приводит `TenantMembership`/`TenantUserRole(ADMIN)` для `credential.service_user` в соответствие с `credential.tenants.all()`: создаёт недостающие, деактивирует/удаляет лишние (для тенантов, убранных из M2M). Вызывается при создании и при каждом сохранении credential в admin (после сохранения M2M — см. §4).

### 3. `apps/mcp_server/http/service_key.py` (новый файл) — ASGI-обёртка

`with_service_key_auth(app)`:
- Заголовка `X-Service-Key` нет → пропускает без изменений (обычный `Authorization`-путь).
- Заголовок есть:
  - Парсит `key_prefix`, ищет `McpServiceCredential` (`is_active=True`), сверяет хеш секрета.
  - Невалиден/неактивен → **сразу 401**, `app()` не вызывается, откат на `Authorization` не выполняется.
  - Валиден → минтит `AccessToken.for_user(credential.service_user)` **напрямую** (не через `mcp_jwt_pair_for_user`, чтобы не создавать `RefreshToken`/`OutstandingToken`-запись в БД на каждый HTTP-запрос), ставит кастомный claim `token["svc"] = True`, переписывает заголовок `authorization` в ASGI `scope` на `Bearer <token>`, обновляет `last_used_at` (best-effort, `aupdate`).
- Подключается в `apps/mcp_server/http/app.py::get_mcp_asgi_app()`: `with_mcp_resource_metadata(with_service_key_auth(mcp.streamable_http_app()))` — сервисный ключ должен переписать заголовок **до** того, как FastMCP/`KolbergOAuthProvider` увидят запрос.

### 4. `apps/mcp_server/admin.py` — регистрация `McpServiceCredential`

- `save_model`: при создании (`obj.pk is None`) вызывает `provision_service_credential`, показывает raw-ключ через `self.message_user(..., level=messages.WARNING)`.
- `save_related`: после того как Django admin сохранил M2M `tenants`, вызывает `sync_tenant_access(obj)` — чтобы правки списка тенантов у существующего ключа тоже применялись.

### 5. `apps/mcp_server/auth.py` — минимальное дополнение

Никаких изменений в `require_module_access` / `require_admin_access` / `require_admin_or_director` не требуется в части ролевой логики (service-user реально admin — проверки просто проходят). Единственная правка — устранить утечку "существует ли чужой тенант" через различие сообщений:

- Новая функция `_is_service_claim(token: str) -> bool` — читает claim `svc` из уже расшифрованного `AccessToken`, не меняя контракт `_decode_token` (важно: `_decode_token` используется в `oauth/provider.py` и замокан в существующих тестах как возвращающий голый `int` — трогать его сигнатуру нельзя).
- `_get_user_and_tenant(user_id, tenant_id, *, service_mode: bool = False)`: оборачивает существующее тело в `try/except PermissionError` — если `service_mode=True`, любая из веток (user not found, tenant not found/inactive, mcp not enabled, not a member) перевыпускается как **одно и то же** сообщение `f"Access denied: tenant {tenant_id} is not accessible with this key"`. Для человека (`service_mode=False`, значение по умолчанию) — поведение и сообщения не меняются ни на символ.
- `require_module_access`/`require_admin_access`/`require_admin_or_director` — добавляют `service_mode = _is_service_claim(token)` и передают его в `_get_user_and_tenant`.

## Error handling

| Ситуация | Поведение |
|---|---|
| `X-Service-Key` не найден по префиксу или хеш не совпал | `401`, JSON `{"error": "Invalid or inactive service key"}`, запрос дальше не идёт |
| `X-Service-Key` валиден, но `tenant_id` не в наборе credential (в т.ч. несуществующий tenant_id) | `PermissionError: Access denied: tenant {id} is not accessible with this key` — **одинаковый ответ** независимо от причины (нет тенанта / тенант неактивен / mcp выключен / нет членства) |
| Ни `X-Service-Key`, ни `Authorization` | Без изменений от текущего поведения (`No authentication token available...`) |
| `Authorization` JWT невалиден/просрочен | Без изменений (`Invalid or expired token: ...`) |
| Тенант в списке credential, но у тенанта выключен нужный модуль (`TenantModuleConfig.is_enabled=False`) | Тот же уникальный `Access denied: tenant {id}...` (не различаем "модуль выключен" от "нет доступа" в service-режиме — той же логикой, что и выше) |

## Testing

- Юнит `McpServiceCredential`/`services.py`: `provision_service_credential` создаёт service_user (unusable password), корректный key roundtrip (генерация → хеш → проверка), `sync_tenant_access` создаёт/деактивирует членства при изменении `tenants` M2M.
- Юнит `auth.py`: `_is_service_claim` — true для токена с `svc=True`, false для обычного JWT; `_get_user_and_tenant(..., service_mode=True)` — все 4 failure-веток дают идентичное сообщение; `service_mode=False` (default) — существующие тесты (`McpTenantToggleTests`) не трогать, должны остаться зелёными без изменений.
- Интеграционный (`Client`, по образцу `McpOAuthMetadataTests`): ключ, привязанный к тенанту A — все тулы работают для A; тул с `tenant_id=B` (существующий чужой) и `tenant_id=999999` (несуществующий) дают байт-в-байт одинаковую ошибку.
- Интеграционный: `X-Service-Key` с неверным секретом → `401`, тело не пытается декодировать как JWT.
- Регрессия: `McpTenantToggleTests`, `McpOAuthMetadataTests`, `McpOAuthLoginFlowTests`, `McpHttpDisabledTests` остаются зелёными без изменений кода тестов.

## Rollout

1. Ветка `dev/mcp-tenant-header-auth` в свободном worktree-слоте (уже создана в `.worktrees/slot-2`).
2. Миграция `apps/mcp_server`: `McpServiceCredential` (`make makemigrations`, не локально).
3. `services.py`, `http/service_key.py`, правки `auth.py` и `admin.py`.
4. `make push` → PR → зелёный CI (`Backend Tests`) → merge.
5. Включение `MCP_HTTP_ENABLED=true` на проде + Traefik-роутер — по чек-листу "To re-enable later" в `docs/MCP_SERVER.md`, отдельный явно запрашиваемый шаг `make deploy`, не автоматический.
6. Обновить `docs/MCP_SERVER.md`: убрать пометку "parked" (или уточнить, что теперь два режима авторизации), задокументировать `X-Service-Key`.

## Follow-ups (out of v1)

- TTL / плановая ротация сервисных ключей.
- Полный аудит-лог вызовов по ключу (не только `last_used_at`).
- Rate-limit на сервисный режим отдельно от человеческого трафика.
