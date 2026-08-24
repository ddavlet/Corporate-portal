# MCP-сервер: сервисная авторизация по заголовку + OAuth для User-режима

- **Date:** 2026-08-24
- **Status:** draft for review
- **Target:** `backend_v2/apps/mcp_server/` (см. `docs/MCP_SERVER.md`) — сейчас "parked" (stdio + `KOLBERG_JWT_TOKEN` env var, HTTP выключен)
- **Clients:** сервисные интеграции (n8n, другие бэкенды, AI-агенты) + люди через Cursor / Claude Desktop / Claude.ai web

## Context

`apps/mcp_server` — read-only MCP-сервер с 17 тулами по бизнес-данным Kolberg (заявки, касса, банк, корп. карта, ЗП, справочники). Multi-tenant платформа: один тенант = одна компания-клиент.

Сегодня единственный способ авторизации — `KOLBERG_JWT_TOKEN`, читается **один раз при старте процесса** (stdio-транспорт, один сервер = одна личность на всё время жизни процесса). Внутри каждого вызова `tenant_id` передаётся явным аргументом и проверяется по `TenantMembership` + ролевой/модульной матрице (`apps/tenants/permissions.py`).

Эта модель не годится для двух новых сценариев:

1. **Сервисные интеграции** (n8n-воркфлоу, другой бэкенд, AI-агент, работающий не от имени конкретного человека) — им не нужен пользовательский аккаунт с ролями, им нужен долгоживущий ключ, который открывает доступ строго к заранее определённому набору тенантов.
2. **HTTP-транспорт** — заголовок вместо env var подразумевает переход на HTTP (сейчас parked), и сервер должен обслуживать много одновременных identities вместо одной на процесс.

## Goals

- Ввести **service-режим** авторизации: HTTP-заголовок `X-Service-Key`, ключ хранится в БД, привязан к множеству тенантов. Доступны **все** 17 тулов (включая admin-only: `get_integration_config`, `list_user_roles`, `list_memberships`) — единственное ограничение — список тенантов.
- Полная изоляция: сервисный ключ не может ни прочитать данные чужого тенанта, ни узнать через различие в ошибках, что чужой тенант вообще существует.
- Перевести существующий **user-режим** (JWT) с env var на `Authorization: Bearer <JWT>` за запрос — HTTP допускает много identities одновременно без рестарта процесса.
- Добавить **OAuth-обвес** для user-режима, чтобы claude.ai (web) подключался кнопкой Connect без ручного ввода заголовков (там не гарантирована поддержка custom headers у коннектора).
- Всё это работает на multi-worker Gunicorn-деплое Django (не single-process, как контейнеры `kolberg-mcp`).

## Non-goals

- Изменение ролевой/модульной матрицы или списка тулов.
- Write-доступ любого рода — сервер остаётся read-only.
- TTL/автоматическая ротация сервисных ключей по расписанию — отзыв только через `is_active=False`.
- Полный аудит-лог каждого вызова — только `last_used_at` на credential.
- OAuth-обвес для service-режима — сервисные ключи всегда статичны, без интерактивного логина.

## Architecture

```
                    ┌─ X-Service-Key: <key> ──────► ServiceAuthContext
                    │                                (tenant_ids из БД, все тулы, без ролей)
HTTP request ───────┤
                    └─ Authorization: Bearer <JWT> ► UserAuthContext
                       (из ручного заголовка ИЛИ    (существующая логика: membership + роль/модуль)
                        из OAuth-обмена — не отличимо)

claude.ai (web, без custom headers)
        │  OAuth Authorization Code + PKCE (Dynamic Client Registration)
        ▼
/oauth/login  →  proxies to  →  POST /api/auth/token/  (существующий Kolberg login)
        │  возвращает реальный SimpleJWT access+refresh как есть
        ▼
claude.ai хранит access_token/refresh_token, дальше шлёт их как обычный
Authorization: Bearer <JWT> — сервер не различает источник токена.
```

Приоритет проверки заголовков: если `X-Service-Key` присутствует — используется он, **fail closed** при невалидности (без отката на JWT). Если заголовка нет — обычный путь через `Authorization`.

## Components

### 1. `McpServiceCredential` (новая модель, БД)

| Поле | Назначение |
|---|---|
| `key_prefix` | Индексированный короткий префикс ключа — O(1) lookup без сканирования хешей |
| `key_hash` | Хеш секретной части ключа (`django.contrib.auth.hashers.make_password` или эквивалент) |
| `name` | Человекочитаемое имя интеграции (для admin) |
| `tenants` | M2M на `Tenant` — разрешённый набор |
| `is_active` | Отзыв без передеплоя |
| `created_at`, `last_used_at` | Аудит по минимуму |

Формат выдаваемого ключа: `svc_<key_prefix>_<секрет>` (аналог GitHub PAT). Управление — через Django admin (`admin.py` регистрация как у остальных моделей проекта).

### 2. `apps/mcp_server/auth.py` — расширение

- `resolve_auth_context(headers) -> AuthContext` — точка входа, вызывается один раз на запрос (не на каждый тул).
- `ServiceAuthContext(tenant_ids: set[int])` — новый класс.
- `UserAuthContext(user, ...)` — оборачивает существующую логику декодирования JWT + резолва `TenantMembership`, без изменений в самой проверке, меняется только источник токена (заголовок вместо env var).
- Существующая точка вызова в каждом туле (`check_access(...)`) принимает `context` вместо `user_id`:
  - `ServiceAuthContext` → единственная проверка: `tenant_id in context.tenant_ids and Tenant.objects.filter(id=tenant_id, is_active=True).exists()`. Роли и `TenantModuleConfig` не проверяются — это осознанное решение (см. Goals).
  - `UserAuthContext` → без изменений: membership + роль/модуль-матрица.

### 3. OAuth-обвес (только для user-режима, только для клиентов без поддержки custom headers)

Переиспользует `OAuthAuthorizationServerProvider` из `mcp` SDK — тот же паттерн, что уже есть в `kolberg-mcp/mcp_ud_report/main.py` (`UDOAuthProvider`), но с двумя отличиями, критичными для этого деплоя:

- **Логин-форма не имеет своего пароля.** `/oauth/login` — HTML-форма логин/пароль, POST проксируется в существующий `POST /api/auth/token/`. При успехе Kolberg-бэкенд возвращает настоящий SimpleJWT access+refresh — обвес возвращает его claude.ai **без переподписи и без своего токен-формата**. Дальнейшие вызовы тулов идут по тому же коду, что и ручной `Authorization` заголовок — сервер не различает источник.
- **Refresh** — не своя логика, а обычный `POST /api/auth/token/refresh/` (стандартный SimpleJWT-эндпоинт; завести, если ещё не существует).
- **DCR-клиенты (`register_client`) — в БД**, не в памяти процесса. Новая модель `McpOAuthClient` (client_id, client_info JSON, created_at). В `mcp_ud_report` это был файловый `TokenStore`, но там сервис однопроцессный; здесь Django/Gunicorn с несколькими воркерами — регистрация на воркере A должна быть видна воркеру B.
- **Authorization codes** (живут 10 минут) — в Django `cache` (Redis, если уже настроен в проекте) с TTL. Локальный `dict`, как в `mcp_ud_report`, здесь не работает по той же причине (multi-worker).

### 4. HTTP-транспорт

Требует включения `MCP_HTTP_ENABLED` (сейчас `false`, см. `docs/MCP_SERVER.md`) — предпосылка всего дизайна, не отдельная задача.

## Data flow

1. Запрос приходит на HTTP MCP endpoint.
2. `resolve_auth_context` читает заголовки:
   - `X-Service-Key` есть → лукап по `key_prefix` в БД → сверка хеша → `is_active` → `ServiceAuthContext`. Если ключ невалиден — сразу `PermissionError`, `Authorization` не проверяется.
   - Иначе `Authorization: Bearer <JWT>` есть → декод SimpleJWT → `UserAuthContext`.
   - Ни одного заголовка → `PermissionError`.
3. Тул вызывается с `tenant_id` первым аргументом, как сейчас.
4. `check_access(context, tenant_id, requirement)` — ветвление по типу контекста (см. Components §2).
5. `last_used_at` у `McpServiceCredential` обновляется best-effort (не блокирует ответ, ошибка обновления не должна валить запрос).
6. Тул выполняется, единый error envelope при ошибке — без изменений от текущего поведения.

## Error handling

| Ситуация | Поведение |
|---|---|
| Нет ни `X-Service-Key`, ни `Authorization` | `PermissionError: Authorization required: Bearer <JWT> or X-Service-Key` |
| `X-Service-Key` невалиден/неактивен | `PermissionError: Invalid or inactive service key` — без отката на JWT |
| `X-Service-Key` валиден, но `tenant_id` не в наборе credential | `PermissionError: Access denied: tenant {id} is not accessible with this key` — **одинаковый ответ** независимо от того, существует ли тенант {id} вообще (проверка набора идёт раньше любого обращения к БД за существованием тенанта — не должно быть oracle для перебора чужих tenant_id) |
| `Authorization` JWT невалиден/просрочен | Без изменений от текущего поведения (`Invalid or expired token: ...`) |
| OAuth: неверный логин/пароль на `/oauth/login` | Форма перерисовывается с ошибкой, `t` (подписанный state) переиспользуется, как в `mcp_ud_report` |

## Testing

- Юнит: `McpServiceCredential` — генерация ключа, roundtrip хеша, lookup по `key_prefix`, инвалидность после `is_active=False`.
- Юнит: `resolve_auth_context` — валидный/просроченный JWT, валидный/невалидный/неактивный service-key, оба заголовка одновременно (service выигрывает), ни одного.
- Интеграционный: ключ, привязанный к тенанту A — не проходит НИ ОДИН из 17 тулов с `tenant_id=B` (в т.ч. несуществующий B); проходит все 17 (включая admin-only) для тенанта A.
- Интеграционный: два ответа на "чужой" `tenant_id` (существующий чужой vs несуществующий) идентичны байт-в-байт.
- Регрессия: существующие тесты ролевой/модульной матрицы для user-режима остаются зелёными без изменений логики.
- OAuth: DCR-регистрация видна между двумя "воркерами" (симулировать двумя процессами/потоками с раздельным кешем клиента); authorization code, выданный в одном процессе, обменивается в другом (через общий cache).

## Rollout

1. Ветка `dev/mcp-tenant-header-auth` в свободном worktree-слоте (см. `CLAUDE.md`).
2. Миграция: `McpServiceCredential`, `McpOAuthClient` (`make makemigrations`, не локально).
3. Реализация `resolve_auth_context`, `ServiceAuthContext`, обновление точек вызова в `tools/*`.
4. OAuth-провайдер + `/oauth/login`, проксирующий в `POST /api/auth/token/`.
5. Включение `MCP_HTTP_ENABLED` + Traefik-роутер (см. чек-лист "To re-enable later" в `docs/MCP_SERVER.md`) — отдельный, явно запрашиваемый шаг деплоя, не автоматический.
6. `make push` → PR → зелёный CI (`Backend Tests`) → merge → `make deploy` (только вручную, по запросу).
7. Обновить `docs/MCP_SERVER.md`: убрать пометку "parked", описать оба режима авторизации, добавить пример конфига для сервисного ключа.

## Follow-ups (out of v1)

- TTL / плановая ротация сервисных ключей.
- Полный аудит-лог вызовов по ключу (не только `last_used_at`).
- Отдельный rate-limit на service-режим, если объём вызовов от интеграций окажется значительно выше человеческого трафика.
