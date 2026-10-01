# Тенантный MCP — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести доменный MCP с общего `https://api.kolberg.uz/mcp` на адрес каждой компании `https://<subdomain>.kolberg.uz/mcp` с токенами, привязанными к тенанту, и фильтрацией инструментов по модулям и роли.

**Architecture:** Один `MCPServer` обслуживает все поддомены. `config/asgi.py` резолвит тенант из `Host`, кладёт его в contextvar и отдаёт метаданные OAuth для хоста. Декоратор инструментов убирает `tenant_id` из схемы и подставляет тенант из контекста; подкласс `MCPServer` фильтрует `list_tools`/`call_tool` по декларации `Access`. JWT получает claim `mcp_tenant_id`, который сверяется с хостом; портал такие токены отклоняет.

**Tech Stack:** Django 5 + DRF + simplejwt, `mcp` Python SDK 2.x (`MCPServer`, streamable HTTP, OAuth provider), Traefik (docker compose labels), PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-09-30-tenant-mcp-design.md`

## Global Constraints

- Коммиты только в ветку `dev/tenant-mcp` (worktree `.worktrees/slot-3`); в `main` — только через PR.
- **Локальные тесты запрещены** (`pytest`, `manage.py test`, `npm test`). Тесты проверяются в GitHub Actions `Backend Tests`, который запускается **только на PR** → PR открывается черновиком в Task 1, каждый `make push` перезапускает CI. «Запустить тест» в шагах = `make push` + `gh pr checks <PR>`; ожидаемый результат указан в шаге.
- Миграции ветки пишутся вручную (не `makemigrations` локально), без удаления данных.
- Код/скрипты, удаляющие данные из БД, запрещены.
- Тексты ошибок инструментов MCP — на английском; описания инструментов — на английском.
- Каждый багфикс/критический сценарий — минимум 1 тест.
- Не вводить новых точек интеграции и новых слоёв (`controllers/`, `repositories/`).
- `make deploy` запускает только пользователь.

## Review Focus

- **Хост в верхнем регистре или с портом** (`LemonFit.kolberg.uz:443`) — должен резолвиться в тот же тенант. Тест в Task 1 (`resolve_mcp_tenant`).
- **Запрос без заголовка `Origin`** (n8n, серверные клиенты ChatGPT) — должен проходить; с чужим `Origin` — 403. Тест в Task 2.
- **Пользователь, у которого отозвали членство после выдачи токена** — `list_tools` должен вернуть пустой список, а не «always»-инструменты. Тест в Task 5 (`test_non_member_sees_nothing`).
- **Refresh-токен, выданный до релиза (без claim)** — обмен должен отклоняться, а не падать 500. Тест в Task 4 (`test_refresh_without_claim_rejected`).
- **`resource` с завершающим `/`** (`https://lemonfit.kolberg.uz/mcp/`) — должен считаться совпадающим. Тест в Task 4 (`test_authorize_accepts_resource_with_trailing_slash`).

---

## Task 0: Гонка `migrate` в `deploy.sh` (отдельная ветка и PR)

Делается **до** тенантного MCP, в своей ветке `fix/deploy-migrate-race` от `main`, в том же слоте `.worktrees/slot-3`. План и спека уже закоммичены в `dev/tenant-mcp`; переключиться: `git fetch origin && git checkout -b fix/deploy-migrate-race origin/main`. `git stash` не использовать.

**Files:**
- Modify: `deploy.sh:40-46`

**Interfaces:** нет (shell).

- [ ] **Step 1: Заменить блок пересоздания + миграции**

Было (`deploy.sh:40-46`):
```bash
docker compose --env-file ./.env up -d --no-deps --force-recreate backend_v2
...
docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate
                          # применяем новые миграции к БД
```
Стало:
```bash
docker compose --env-file ./.env up -d --no-deps --force-recreate backend_v2
                          # пересоздаём контейнер бека — подхватывает новый образ и env-переменные из .env
                          # --force-recreate: bind-mount код не меняет image-digest, поэтому без него docker
                          # считает контейнер актуальным и не перезапускает gunicorn

# Команда контейнера сама запускает `migrate` при старте. Ждём, пока она закончит,
# иначе наш `exec migrate` ниже гоняется с ней за те же таблицы и падает
# (duplicate pg_type / column already exists) — деплой обрывался посередине.
echo "Жду окончания стартовой миграции backend_v2..."
for i in $(seq 1 60); do
  if docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate --check >/dev/null 2>&1; then
    echo "Стартовая миграция завершена."
    break
  fi
  sleep 3
done

docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate
                          # применяем оставшиеся миграции (обычно no-op; при таймауте покажет реальную ошибку)
```

- [ ] **Step 2: Проверить синтаксис**

Run: `bash -n deploy.sh && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit, push, PR**

```bash
git add deploy.sh
git commit -m "fix(deploy): wait for container startup migrate before exec migrate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make push
gh pr create --base main --head fix/deploy-migrate-race --title "fix(deploy): гонка двух migrate при деплое" --body "..."
```
CI `Backend Tests` на этот PR не запустится (путь не в `backend_v2/**`) — это нормально. Проверка — на следующем `make deploy` (в выводе должна быть строка «Стартовая миграция завершена.»).

- [ ] **Step 4: Вернуться в `dev/tenant-mcp`**

```bash
git checkout dev/tenant-mcp
```

---

## Task 1: Контекст тенанта и маршрутизация по поддомену

**Files:**
- Create: `backend_v2/apps/mcp_server/tenant_context.py`
- Modify (переписать целиком): `backend_v2/apps/mcp_server/routing.py`
- Modify: `backend_v2/apps/tenants/middleware.py:82-85` (убрать исключение для MCP-хоста)
- Test: `backend_v2/apps/mcp_server/tests.py` (импорты вверху; заменить `McpRoutingTests`; удалить `McpOAuthMetadataTests`, `McpOAuthLoginFlowTests` — они проверяют `api.kolberg.uz`, заменяются в Task 2/4)

**Interfaces:**
- Produces:
  - `McpTenant(id: int, subdomain: str, name: str)` — frozen dataclass; свойства `origin: str` (`https://<sub>.<BASE_DOMAIN>`), `base_url: str` (`<origin>/mcp`).
  - `tenant_origin(subdomain: str) -> str`
  - `resolve_mcp_tenant(host: str) -> McpTenant | None` (sync, ORM)
  - `set_current_tenant(t: McpTenant | None) -> contextvars.Token`, `reset_current_tenant(token) -> None`, `current_tenant() -> McpTenant` (raises `PermissionError` если не задан)
  - `origin_allowed(origin: str | None, tenant: McpTenant) -> bool`
  - `routing.py`: `mcp_http_enabled()`, `path_normalized(path)`, `is_well_known_oauth_path(path)`, `is_well_known_authorization_server_path(path)`, `is_mcp_login_path(path)`, `is_mcp_protocol_path(path)`, `is_tenant_mcp_path(path)`

- [ ] **Step 1: Открыть черновой PR (для CI)**

```bash
cd .worktrees/slot-3
make push
gh pr create --draft --base main --head dev/tenant-mcp \
  --title "feat(mcp): MCP на поддомене каждой компании" \
  --body "Спека: docs/superpowers/specs/2026-09-30-tenant-mcp-design.md. План: docs/superpowers/plans/2026-09-30-tenant-mcp.md. WIP."
```
Запомнить номер PR (`<PR>`).

- [ ] **Step 2: Написать падающие тесты**

В `tests.py` заменить блок импорта `from apps.mcp_server.routing import (...)` на:
```python
from apps.mcp_server.routing import (
    is_mcp_login_path,
    is_mcp_protocol_path,
    is_tenant_mcp_path,
    is_well_known_oauth_path,
    mcp_http_enabled,
)
```
Заменить класс `McpRoutingTests` целиком и удалить классы `McpOAuthMetadataTests`, `McpOAuthLoginFlowTests` и константу `_MCP_TEST_HOST`:
```python
class McpRoutingTests(TestCase):
    def test_protocol_paths(self):
        for path in ("/mcp", "/mcp/", "/mcp/authorize", "/mcp/token", "/mcp/register"):
            self.assertTrue(is_mcp_protocol_path(path), path)

    def test_login_path(self):
        self.assertTrue(is_mcp_login_path("/mcp/login/"))
        self.assertTrue(is_mcp_login_path("/mcp/login"))
        self.assertFalse(is_mcp_login_path("/oauth/login/"))

    def test_well_known_paths(self):
        for path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-authorization-server/mcp",
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp/",
        ):
            self.assertTrue(is_well_known_oauth_path(path), path)
        self.assertFalse(is_well_known_oauth_path("/mcp/.well-known/oauth-authorization-server"))

    def test_tenant_mcp_path_covers_protocol_and_discovery_only(self):
        self.assertTrue(is_tenant_mcp_path("/mcp/"))
        self.assertTrue(is_tenant_mcp_path("/.well-known/oauth-protected-resource"))
        self.assertFalse(is_tenant_mcp_path("/api/requests/"))
        self.assertFalse(is_tenant_mcp_path("/app/"))


@override_settings(BASE_DOMAIN="kolberg.uz", MCP_ALLOWED_ORIGINS=["https://claude.ai"])
class McpTenantContextTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant

        self.tenant = Tenant.objects.create(name="Lemon", subdomain="lemonctx", is_active=True, mcp_enabled=True)

    def test_resolves_enabled_tenant_from_host(self):
        from apps.mcp_server.tenant_context import resolve_mcp_tenant

        t = resolve_mcp_tenant("lemonctx.kolberg.uz")
        self.assertEqual((t.id, t.subdomain, t.name), (self.tenant.id, "lemonctx", "Lemon"))
        self.assertEqual(t.base_url, "https://lemonctx.kolberg.uz/mcp")

    def test_host_case_and_port_are_ignored(self):
        from apps.mcp_server.tenant_context import resolve_mcp_tenant

        self.assertEqual(resolve_mcp_tenant("LemonCtx.Kolberg.uz:443").id, self.tenant.id)

    def test_disabled_inactive_unknown_resolve_to_none(self):
        from apps.mcp_server.tenant_context import resolve_mcp_tenant
        from apps.tenants.models import Tenant

        Tenant.objects.create(name="Off", subdomain="offctx", is_active=True, mcp_enabled=False)
        Tenant.objects.create(name="Gone", subdomain="gonectx", is_active=False, mcp_enabled=True)
        for host in ("offctx.kolberg.uz", "gonectx.kolberg.uz", "nope.kolberg.uz", "api.kolberg.uz", "kolberg.uz"):
            self.assertIsNone(resolve_mcp_tenant(host), host)

    def test_current_tenant_requires_binding(self):
        from apps.mcp_server.tenant_context import (
            McpTenant, current_tenant, reset_current_tenant, set_current_tenant,
        )

        with self.assertRaises(PermissionError):
            current_tenant()
        token = set_current_tenant(McpTenant(id=7, subdomain="x", name="X"))
        try:
            self.assertEqual(current_tenant().id, 7)
        finally:
            reset_current_tenant(token)
        with self.assertRaises(PermissionError):
            current_tenant()

    def test_origin_rules(self):
        from apps.mcp_server.tenant_context import McpTenant, origin_allowed

        t = McpTenant(id=1, subdomain="lemonctx", name="L")
        self.assertTrue(origin_allowed(None, t))
        self.assertTrue(origin_allowed("", t))
        self.assertTrue(origin_allowed("https://claude.ai", t))
        self.assertTrue(origin_allowed("https://lemonctx.kolberg.uz", t))
        self.assertFalse(origin_allowed("https://evil.example", t))
        self.assertFalse(origin_allowed("https://other.kolberg.uz", t))
```

- [ ] **Step 3: Запустить тесты — ожидается падение**

Run: `git add -A && git commit -m "test(mcp): tenant context and routing" && make push && gh pr checks <PR> --watch`
Expected: FAIL — `ImportError: cannot import name 'is_mcp_login_path'`.

- [ ] **Step 4: Реализовать `tenant_context.py`**

```python
"""Tenant of the current MCP request, resolved from the Host subdomain.

config/asgi.py binds it for every /mcp and /.well-known/oauth-* request on a
tenant host; tools, the OAuth provider and the service-key middleware read it.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class McpTenant:
    id: int
    subdomain: str
    name: str

    @property
    def origin(self) -> str:
        return tenant_origin(self.subdomain)

    @property
    def base_url(self) -> str:
        return f"{self.origin}/mcp"


_current: contextvars.ContextVar[McpTenant | None] = contextvars.ContextVar("mcp_tenant", default=None)


def tenant_origin(subdomain: str) -> str:
    base = (getattr(settings, "BASE_DOMAIN", "") or "localhost").strip(".").lower()
    scheme = "http" if base in ("localhost", "127.0.0.1") else "https"
    return f"{scheme}://{subdomain}.{base}"


def set_current_tenant(tenant: McpTenant | None) -> contextvars.Token:
    return _current.set(tenant)


def reset_current_tenant(token: contextvars.Token) -> None:
    _current.reset(token)


def current_tenant() -> McpTenant:
    tenant = _current.get()
    if tenant is None:
        raise PermissionError("MCP tenant is not resolved for this request")
    return tenant


def resolve_mcp_tenant(host: str) -> McpTenant | None:
    """Active, MCP-enabled tenant for a host like 'lemonfit.kolberg.uz', else None."""
    from apps.tenants.middleware import _get_subdomain
    from apps.tenants.models import Tenant

    sub = _get_subdomain((host or "").lower(), getattr(settings, "BASE_DOMAIN", "") or "")
    if not sub:
        return None
    row = (
        Tenant.objects.filter(subdomain=sub, is_active=True, mcp_enabled=True)
        .values("id", "subdomain", "name")
        .first()
    )
    return McpTenant(**row) if row else None


def origin_allowed(origin: str | None, tenant: McpTenant) -> bool:
    """No Origin (server-to-server) is allowed; a browser Origin must be listed."""
    if not origin:
        return True
    allowed = {o.rstrip("/") for o in settings.MCP_ALLOWED_ORIGINS} | {tenant.origin}
    return origin.rstrip("/") in allowed
```

Проверить `_get_subdomain` для верхнего регистра: он вызывает `_host_no_port`, который обрезает порт; регистр нормализуем сами (`.lower()` выше).

- [ ] **Step 5: Переписать `routing.py`**

```python
"""
MCP routing on tenant hosts (https://<subdomain>.<BASE_DOMAIN>).

  /.well-known/oauth-*[/mcp] → OAuth discovery JSON for the host (config/asgi.py)
  /mcp/login/                → Django OTP login bound to the tenant
  /mcp, /mcp/*               → MCP app (protocol + OAuth endpoints)
"""

from __future__ import annotations

from django.conf import settings

_WELL_KNOWN_AUTHORIZATION_SERVER = frozenset(
    {"/.well-known/oauth-authorization-server", "/.well-known/oauth-authorization-server/mcp"}
)
_WELL_KNOWN_PROTECTED_RESOURCE = frozenset(
    {"/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"}
)


def path_normalized(path: str) -> str:
    return (path or "/").rstrip("/") or "/"


def mcp_http_enabled() -> bool:
    """HTTP/OAuth MCP surface is off unless MCP_HTTP_ENABLED is set."""
    return bool(getattr(settings, "MCP_HTTP_ENABLED", False))


def is_well_known_authorization_server_path(path: str) -> bool:
    return path_normalized(path) in _WELL_KNOWN_AUTHORIZATION_SERVER


def is_well_known_oauth_path(path: str) -> bool:
    p = path_normalized(path)
    return p in _WELL_KNOWN_AUTHORIZATION_SERVER or p in _WELL_KNOWN_PROTECTED_RESOURCE


def is_mcp_login_path(path: str) -> bool:
    return path_normalized(path) == "/mcp/login"


def is_mcp_protocol_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


def is_tenant_mcp_path(path: str) -> bool:
    return is_mcp_protocol_path(path) or is_well_known_oauth_path(path)
```

- [ ] **Step 6: Убрать исключение MCP-хоста из `TenantSubdomainMiddleware`**

В `backend_v2/apps/tenants/middleware.py` удалить строки:
```python
        from apps.mcp_server.routing import is_mcp_host

        if is_mcp_host(request.get_host()):
            return self.get_response(request)

```

- [ ] **Step 7: Запустить тесты**

Run: `git add -A && git commit -m "feat(mcp): resolve MCP tenant from host subdomain" && make push && gh pr checks <PR> --watch`
Expected: PASS (`Backend Tests`). `config/asgi.py` продолжает импортировать `is_mcp_protocol_path`, `is_well_known_oauth_path`, `is_well_known_authorization_server_path` — они сохранены.

---

## Task 2: Метаданные OAuth для хоста и тенантная ветка в `asgi.py`

**Files:**
- Modify: `backend_v2/apps/mcp_server/oauth/metadata.py` (функции получают `base_url`/`origin`)
- Modify: `backend_v2/apps/mcp_server/http/middleware.py` (URL метаданных из текущего тенанта)
- Modify: `backend_v2/config/asgi.py` (функция `application`, новая `_tenant_mcp`)
- Delete: `backend_v2/apps/mcp_server/oauth/metadata_views.py`
- Modify: `backend_v2/config/urls.py` (убрать два маршрута `.well-known/...` и их импорт)
- Test: `backend_v2/apps/mcp_server/tests.py` (новый класс `McpTenantAsgiTests`)

**Interfaces:**
- Consumes: Task 1 — `resolve_mcp_tenant`, `origin_allowed`, `set_current_tenant`, `reset_current_tenant`, `current_tenant`, `McpTenant.base_url`, `McpTenant.origin`, `is_tenant_mcp_path`, `is_mcp_login_path`, `is_well_known_*`.
- Produces:
  - `authorization_server_metadata(base_url: str) -> dict`
  - `protected_resource_metadata(base_url: str) -> dict`
  - `protected_resource_metadata_url(origin: str) -> str`
  - `mcp_oauth_login_url()` **остаётся** до Task 4 (им пользуется `provider.py`).

- [ ] **Step 1: Написать падающие тесты**

```python
@override_settings(MCP_HTTP_ENABLED=True, BASE_DOMAIN="kolberg.uz", MCP_ALLOWED_ORIGINS=["https://claude.ai"])
class McpTenantAsgiTests(TestCase):
    """config.asgi.application on tenant hosts: tenant resolution, discovery, origin, dispatch."""

    def setUp(self):
        from apps.tenants.models import Tenant

        self.tenant = Tenant.objects.create(name="Lemon", subdomain="lemonasgi", is_active=True, mcp_enabled=True)
        Tenant.objects.create(name="Off", subdomain="offasgi", is_active=True, mcp_enabled=False)

    def _call(self, host, path, extra_headers=(), mcp_app=None):
        import json
        from asgiref.sync import async_to_sync
        from config.asgi import application

        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
            "root_path": "", "query_string": b"", "scheme": "https",
            "headers": [(b"host", host.encode())] + list(extra_headers),
        }
        if mcp_app is None:
            async_to_sync(application)(scope, receive, send)
        else:
            with patch("apps.mcp_server.http.app.get_mcp_asgi_app", return_value=mcp_app):
                async_to_sync(application)(scope, receive, send)
        status = sent[0]["status"]
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        try:
            return status, json.loads(body)
        except ValueError:
            return status, body

    def test_protected_resource_metadata_is_per_host(self):
        status, body = self._call("lemonasgi.kolberg.uz", "/.well-known/oauth-protected-resource")
        self.assertEqual(status, 200)
        self.assertEqual(body["resource"], "https://lemonasgi.kolberg.uz/mcp")
        self.assertEqual(body["authorization_servers"], ["https://lemonasgi.kolberg.uz/mcp"])

    def test_authorization_server_metadata_is_per_host(self):
        status, body = self._call("lemonasgi.kolberg.uz", "/.well-known/oauth-authorization-server/mcp")
        self.assertEqual(status, 200)
        self.assertEqual(body["issuer"], "https://lemonasgi.kolberg.uz/mcp")
        self.assertEqual(body["authorization_endpoint"], "https://lemonasgi.kolberg.uz/mcp/authorize")
        self.assertEqual(body["token_endpoint"], "https://lemonasgi.kolberg.uz/mcp/token")
        self.assertEqual(body["registration_endpoint"], "https://lemonasgi.kolberg.uz/mcp/register")
        self.assertIn("S256", body["code_challenge_methods_supported"])

    def test_unknown_or_disabled_tenant_is_404(self):
        for host in ("offasgi.kolberg.uz", "nope.kolberg.uz", "api.kolberg.uz"):
            status, _ = self._call(host, "/.well-known/oauth-protected-resource")
            self.assertEqual(status, 404, host)

    def test_foreign_origin_is_403_and_missing_origin_passes(self):
        status, _ = self._call(
            "lemonasgi.kolberg.uz", "/.well-known/oauth-protected-resource",
            extra_headers=[(b"origin", b"https://evil.example")],
        )
        self.assertEqual(status, 403)
        status, _ = self._call("lemonasgi.kolberg.uz", "/.well-known/oauth-protected-resource")
        self.assertEqual(status, 200)

    def test_mcp_path_reaches_app_with_tenant_bound_and_prefix_stripped(self):
        from apps.mcp_server.tenant_context import current_tenant

        seen = {}

        async def fake_mcp(scope, receive, send):
            seen["path"] = scope["path"]
            seen["root_path"] = scope["root_path"]
            seen["tenant_id"] = current_tenant().id
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        status, _ = self._call("lemonasgi.kolberg.uz", "/mcp/token", mcp_app=fake_mcp)
        self.assertEqual(status, 200)
        self.assertEqual(seen, {"path": "/token", "root_path": "/mcp", "tenant_id": self.tenant.id})

    def test_unauthorized_response_points_to_host_metadata(self):
        from apps.mcp_server.http.middleware import with_mcp_resource_metadata

        async def unauthorized(scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        status, _ = self._call("lemonasgi.kolberg.uz", "/mcp/", mcp_app=with_mcp_resource_metadata(unauthorized))
        self.assertEqual(status, 401)

    def test_unauthorized_header_value(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.middleware import with_mcp_resource_metadata
        from apps.mcp_server.tenant_context import McpTenant, reset_current_tenant, set_current_tenant

        sent = []

        async def unauthorized(scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})

        async def send(message):
            sent.append(message)

        token = set_current_tenant(McpTenant(id=self.tenant.id, subdomain="lemonasgi", name="Lemon"))
        try:
            async_to_sync(with_mcp_resource_metadata(unauthorized))({"type": "http"}, None, send)
        finally:
            reset_current_tenant(token)
        header = dict(sent[0]["headers"])[b"www-authenticate"].decode()
        self.assertIn('resource_metadata="https://lemonasgi.kolberg.uz/.well-known/oauth-protected-resource"', header)

    def test_non_mcp_paths_go_to_django(self):
        status, _ = self._call("lemonasgi.kolberg.uz", "/api/definitely-not-a-route/")
        self.assertEqual(status, 404)
```

- [ ] **Step 2: Запустить — ожидается падение**

Run: `git add -A && git commit -m "test(mcp): per-host discovery and asgi tenant branch" && make push && gh pr checks <PR> --watch`
Expected: FAIL — метаданные указывают на `api.kolberg.uz`, `offasgi` не даёт 404.

- [ ] **Step 3: Переписать функции в `oauth/metadata.py`**

Заменить содержимое файла (кроме `mcp_oauth_login_url`, которая остаётся до Task 4):
```python
"""
OAuth discovery documents for MCP clients (Claude, ChatGPT).

For MCP server URL https://<tenant>.kolberg.uz/mcp the discovery documents are
served from the host root (RFC 8414 / RFC 9728); config/asgi.py passes the
tenant's base URL.
"""

from __future__ import annotations

from django.conf import settings


def mcp_oauth_login_url() -> str:
    """Temporary: removed in Task 4 together with the static login URL."""
    return settings.MCP_OAUTH_LOGIN_URL


def authorization_server_metadata(base_url: str) -> dict:
    """RFC 8414 — /.well-known/oauth-authorization-server[/mcp] on the tenant host."""
    base = base_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "scopes_supported": ["mcp"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
    }


def protected_resource_metadata(base_url: str) -> dict:
    """RFC 9728 — /.well-known/oauth-protected-resource[/mcp] on the tenant host."""
    base = base_url.rstrip("/")
    return {
        "resource": base,
        "authorization_servers": [base],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


def protected_resource_metadata_url(origin: str) -> str:
    return f"{origin.rstrip('/')}/.well-known/oauth-protected-resource"
```

- [ ] **Step 4: `http/middleware.py` — URL из текущего тенанта**

```python
"""
ASGI middleware: add MCP resource_metadata hint to 401 responses (RFC 9728).
"""

from __future__ import annotations

from apps.mcp_server.oauth.metadata import protected_resource_metadata_url
from apps.mcp_server.tenant_context import current_tenant


def with_mcp_resource_metadata(app):
    """Wrap an ASGI app so 401 responses point to the tenant host's discovery document."""

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        header_name = b"www-authenticate"
        canonical_meta = protected_resource_metadata_url(current_tenant().origin)

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                headers = [(n, v) for n, v in message.get("headers", []) if n.lower() != header_name]
                headers.append(
                    (
                        header_name,
                        f'Bearer error="invalid_token", error_description="Authentication required", '
                        f'resource_metadata="{canonical_meta}"'.encode("latin-1"),
                    )
                )
                message = {**message, "headers": headers}
            await send(message)

        await app(scope, receive, send_wrapper)

    return middleware
```

- [ ] **Step 5: `config/asgi.py` — тенантная ветка**

Добавить функцию перед `application`:
```python
async def _tenant_mcp(scope, receive, send, path: str) -> None:
    """MCP on a tenant host: resolve tenant, check Origin, bind it, dispatch."""
    from asgiref.sync import sync_to_async

    from apps.mcp_server.routing import (
        is_mcp_login_path,
        is_well_known_authorization_server_path,
        is_well_known_oauth_path,
    )
    from apps.mcp_server.tenant_context import (
        origin_allowed,
        reset_current_tenant,
        resolve_mcp_tenant,
        set_current_tenant,
    )

    headers = dict(scope.get("headers") or [])
    host = headers.get(b"host", b"").decode("latin-1")
    tenant = await sync_to_async(resolve_mcp_tenant, thread_sensitive=True)(host)
    if tenant is None:
        await _send_json(send, {"error": "Not found"}, status=404)
        return

    origin = headers.get(b"origin", b"").decode("latin-1") or None
    if not origin_allowed(origin, tenant):
        await _send_json(send, {"error": "Origin not allowed"}, status=403)
        return

    token = set_current_tenant(tenant)
    try:
        if is_well_known_oauth_path(path):
            from apps.mcp_server.oauth.metadata import (
                authorization_server_metadata,
                protected_resource_metadata,
            )

            if is_well_known_authorization_server_path(path):
                await _send_json(send, authorization_server_metadata(tenant.base_url))
            else:
                await _send_json(send, protected_resource_metadata(tenant.base_url))
            return

        if is_mcp_login_path(path):
            await _django_app(scope, receive, send)
            return

        from apps.mcp_server.http.app import get_mcp_asgi_app

        new_scope = {
            **scope,
            "path": path[4:] or "/",
            "root_path": scope.get("root_path", "") + "/mcp",
        }
        await get_mcp_asgi_app()(new_scope, receive, send)
    finally:
        reset_current_tenant(token)
```
В `application` заменить всё, начиная с `path = scope.get("path", "")` и до конца функции, на:
```python
    path = scope.get("path", "")

    from apps.mcp_server.routing import is_tenant_mcp_path

    if is_tenant_mcp_path(path):
        await _tenant_mcp(scope, receive, send, path)
        return

    await _django_app(scope, receive, send)
```
Обновить docstring модуля: вместо «MCP host routing is:» — «On tenant hosts: /.well-known/oauth-* → per-host JSON, /mcp/login/ → Django, /mcp/* → MCP».

- [ ] **Step 6: Удалить Django-вью метаданных**

```bash
git rm backend_v2/apps/mcp_server/oauth/metadata_views.py
```
В `backend_v2/config/urls.py` удалить импорт
```python
from apps.mcp_server.oauth.metadata_views import (
    AuthorizationServerMetadataView,
    ProtectedResourceMetadataView,
)
```
и два `path(".well-known/...")`. Маршрут `oauth/login/` пока остаётся (Task 4).

- [ ] **Step 7: Запустить тесты**

Run: `git add -A && git commit -m "feat(mcp): per-host OAuth discovery and tenant branch in asgi" && make push && gh pr checks <PR> --watch`
Expected: PASS. `McpHttpDisabledTests` продолжают проходить (маршрутов больше нет → 404).

---

## Task 3: Токены, привязанные к тенанту; портал не принимает MCP-токены; сервисный ключ по тенанту

**Files:**
- Create: `backend_v2/apps/accounts/authentication.py`
- Modify: `backend_v2/config/settings.py:192-194` (`DEFAULT_AUTHENTICATION_CLASSES`)
- Modify: `backend_v2/apps/modules/n8n_integration/authentication.py:28` (миксин)
- Modify: `backend_v2/apps/mcp_server/auth.py` (`_get_token`, `_decode_token`, убрать `KOLBERG_JWT_TOKEN`)
- Modify: `backend_v2/apps/mcp_server/oauth/tokens.py` (`mcp_jwt_pair_for_user(user, tenant_id)`)
- Modify: `backend_v2/apps/mcp_server/http/service_key.py` (проверка тенанта + claim)
- Test: `backend_v2/apps/mcp_server/tests.py` (новые `McpTokenBindingTests`, `PortalRejectsMcpTokenTests`; переписать `ServiceKeyMiddlewareTests`, `ServiceKeyEndToEndTests`)

**Interfaces:**
- Consumes: Task 1 — `current_tenant`, `set_current_tenant`, `reset_current_tenant`, `McpTenant`.
- Produces:
  - `apps.accounts.authentication.MCP_TENANT_CLAIM = "mcp_tenant_id"`
  - `RejectMcpTokenMixin`, `PortalJWTAuthentication`
  - `apps.mcp_server.auth._decode_token(token: str) -> int` — теперь требует claim, равный `current_tenant().id`
  - `apps.mcp_server.oauth.tokens.mcp_jwt_pair_for_user(user, tenant_id: int) -> (RefreshToken, AccessToken)`
  - `apps.mcp_server.http.service_key._mint_service_access_token(service_user, tenant_id: int) -> str`

- [ ] **Step 1: Написать падающие тесты**

Хелпер (положить рядом с новыми классами):
```python
def _bind_tenant(tenant):
    from apps.mcp_server.tenant_context import McpTenant, set_current_tenant

    return set_current_tenant(McpTenant(id=tenant.id, subdomain=tenant.subdomain, name=tenant.name))


def _mcp_access_token(user, tenant_id):
    from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user

    _, access = mcp_jwt_pair_for_user(user, tenant_id)
    return str(access)
```
Новые классы:
```python
class McpTokenBindingTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant

        self.user = get_user_model().objects.create_user(username="bind-user")
        self.a = Tenant.objects.create(name="A", subdomain="bind-a", is_active=True, mcp_enabled=True)
        self.b = Tenant.objects.create(name="B", subdomain="bind-b", is_active=True, mcp_enabled=True)

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def test_token_for_its_tenant_decodes(self):
        from apps.mcp_server.auth import _decode_token

        _bind_tenant(self.a)
        self.assertEqual(_decode_token(_mcp_access_token(self.user, self.a.id)), self.user.id)

    def test_token_for_other_tenant_rejected(self):
        from apps.mcp_server.auth import _decode_token

        _bind_tenant(self.b)
        with self.assertRaisesRegex(PermissionError, "not valid for this company"):
            _decode_token(_mcp_access_token(self.user, self.a.id))

    def test_portal_token_rejected(self):
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.mcp_server.auth import _decode_token

        _bind_tenant(self.a)
        with self.assertRaisesRegex(PermissionError, "not valid for this company"):
            _decode_token(str(AccessToken.for_user(self.user)))

    def test_no_env_token_fallback(self):
        import os
        from apps.mcp_server.auth import _get_token, set_request_token

        set_request_token("")
        with patch.dict(os.environ, {"KOLBERG_JWT_TOKEN": "x"}):
            with self.assertRaises(PermissionError):
                _get_token()


class PortalRejectsMcpTokenTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="portal-user")

    def test_portal_auth_is_default(self):
        from django.conf import settings

        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
            ("apps.accounts.authentication.PortalJWTAuthentication",),
        )

    def test_mcp_token_rejected_by_portal(self):
        from rest_framework_simplejwt.exceptions import InvalidToken
        from apps.accounts.authentication import PortalJWTAuthentication

        with self.assertRaises(InvalidToken):
            PortalJWTAuthentication().get_validated_token(_mcp_access_token(self.user, 1).encode())

    def test_portal_token_still_accepted(self):
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.accounts.authentication import PortalJWTAuthentication

        token = PortalJWTAuthentication().get_validated_token(str(AccessToken.for_user(self.user)).encode())
        self.assertEqual(int(token["user_id"]), self.user.id)

    def test_n8n_integration_auth_rejects_mcp_token(self):
        from apps.accounts.authentication import RejectMcpTokenMixin
        from apps.modules.n8n_integration.authentication import N8nIntegrationAuthentication

        self.assertTrue(issubclass(N8nIntegrationAuthentication, RejectMcpTokenMixin))
```
Переписать `ServiceKeyMiddlewareTests` (setUp и `_run` + тесты):
```python
class ServiceKeyMiddlewareTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant
        from apps.mcp_server.services import provision_service_credential

        self.tenant = Tenant.objects.create(name="MW", subdomain="svc-mw", is_active=True, mcp_enabled=True)
        self.other = Tenant.objects.create(name="MW2", subdomain="svc-mw2", is_active=True, mcp_enabled=True)
        self.credential, self.raw_key = provision_service_credential("mw-test", [self.tenant.id])

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def _run(self, app, headers, tenant=None):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.service_key import with_service_key_auth

        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        _bind_tenant(tenant or self.tenant)
        async_to_sync(with_service_key_auth(app))({"type": "http", "path": "/", "headers": headers}, receive, send)
        return sent

    @staticmethod
    async def _ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    def test_no_header_passes_through_unchanged(self):
        seen = []

        async def downstream(scope, receive, send):
            seen.append(scope)
            await self._ok(scope, receive, send)

        self._run(downstream, headers=[(b"authorization", b"Bearer original")])
        self.assertEqual(seen[0]["headers"], [(b"authorization", b"Bearer original")])

    def test_valid_key_for_bound_tenant_mints_tenant_token(self):
        from apps.mcp_server.auth import _decode_token, _is_service_claim

        seen = []

        async def downstream(scope, receive, send):
            seen.append(scope)
            await self._ok(scope, receive, send)

        self._run(downstream, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])
        token = [v for k, v in seen[0]["headers"] if k == b"authorization"][0].decode().removeprefix("Bearer ")
        self.assertEqual(_decode_token(token), self.credential.service_user_id)
        self.assertTrue(_is_service_claim(token))

    def test_key_not_bound_to_host_tenant_gets_same_401_as_invalid_key(self):
        called = []

        async def downstream(scope, receive, send):
            called.append(True)

        unbound = self._run(downstream, [(b"x-service-key", self.raw_key.encode("latin-1"))], tenant=self.other)
        invalid = self._run(downstream, [(b"x-service-key", b"svc_bad_bad")])
        self.assertEqual(called, [])
        self.assertEqual(unbound[0]["status"], 401)
        self.assertEqual(unbound[1]["body"], invalid[1]["body"])

    def test_valid_key_updates_last_used_at(self):
        self._run(self._ok, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])
        self.credential.refresh_from_db()
        self.assertIsNotNone(self.credential.last_used_at)

    def test_non_http_scope_passes_through(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.service_key import with_service_key_auth

        seen = []

        async def downstream(scope, receive, send):
            seen.append(scope["type"])

        async_to_sync(with_service_key_auth(downstream))({"type": "lifespan"}, None, None)
        self.assertEqual(seen, ["lifespan"])
```
В `ServiceKeyEndToEndTests`: `_minted_token` → `_mint_service_access_token(self.credential.service_user, self.tenant_a.id)`; в начале каждого теста `_bind_tenant(self.tenant_a)`; добавить `tearDown` как выше. `test_service_token_denied_for_out_of_scope_tenant` и `test_service_token_denied_identically_for_nonexistent_tenant` заменить одним:
```python
    def test_service_token_rejected_on_other_tenant_host(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        _bind_tenant(self.tenant_b)
        with self.assertRaisesRegex(PermissionError, "not valid for this company"):
            require_module_access(self.tenant_b.id, "requests")
```
`test_human_jwt_path_is_completely_unaffected` заменить:
```python
    def test_human_mcp_token_works_for_member(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import TenantMembership, TenantUserRole
        from apps.mcp_server.auth import set_request_token, require_module_access

        human = get_user_model().objects.create_user(username="e2e-human")
        TenantMembership.objects.create(user=human, tenant=self.tenant_a, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant_a, user=human, role=TenantUserRole.ROLE_REQUESTER)
        _bind_tenant(self.tenant_a)
        set_request_token(_mcp_access_token(human, self.tenant_a.id))
        user, tenant = require_module_access(self.tenant_a.id, "requests")
        self.assertEqual((user.id, tenant.id), (human.id, self.tenant_a.id))
```

- [ ] **Step 2: Запустить — ожидается падение**

Run: `git add -A && git commit -m "test(mcp): tenant-bound tokens and portal rejection" && make push && gh pr checks <PR> --watch`
Expected: FAIL — `mcp_jwt_pair_for_user() takes 1 positional argument`, `No module named 'apps.accounts.authentication'`.

- [ ] **Step 3: `apps/accounts/authentication.py`**

```python
"""Portal JWT authentication: MCP connector tokens are never accepted here."""

from __future__ import annotations

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

# Set on every JWT issued for an MCP connector (apps/mcp_server/oauth/tokens.py,
# apps/mcp_server/http/service_key.py). Its presence marks a token as MCP-only.
MCP_TENANT_CLAIM = "mcp_tenant_id"


class RejectMcpTokenMixin:
    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)
        if token.get(MCP_TENANT_CLAIM) is not None:
            raise InvalidToken("MCP connector tokens are not accepted by the portal API")
        return token


class PortalJWTAuthentication(RejectMcpTokenMixin, JWTAuthentication):
    pass
```

- [ ] **Step 4: Подключить**

`config/settings.py`:
```python
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.PortalJWTAuthentication",
    ),
```
`apps/modules/n8n_integration/authentication.py`:
```python
from apps.accounts.authentication import RejectMcpTokenMixin
...
class N8nIntegrationAuthentication(RejectMcpTokenMixin, JWTAuthentication):
```

- [ ] **Step 5: `oauth/tokens.py`**

```python
"""JWT pair for MCP OAuth — bound to one tenant, longer lifetime than portal defaults."""

from __future__ import annotations

import os
from datetime import timedelta

from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.authentication import MCP_TENANT_CLAIM


def mcp_jwt_pair_for_user(user, tenant_id: int):
    """Return (refresh, access) carrying mcp_tenant_id, with MCP lifetimes (env-tunable)."""
    access_minutes = int(os.getenv("MCP_ACCESS_TOKEN_MINUTES", "60") or "60")
    refresh_days = int(os.getenv("MCP_REFRESH_TOKEN_DAYS", "7") or "7")

    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=timedelta(days=refresh_days))
    refresh[MCP_TENANT_CLAIM] = int(tenant_id)
    access = refresh.access_token
    access[MCP_TENANT_CLAIM] = int(tenant_id)
    access.set_exp(lifetime=timedelta(minutes=access_minutes))
    return refresh, access
```

- [ ] **Step 6: `auth.py`**

Удалить `import os`, `_ENV_VAR`, упоминания stdio в docstring модуля. Заменить `_get_token` и `_decode_token`:
```python
def _get_token() -> str:
    """JWT of the current request (set by the OAuth provider / service-key middleware)."""
    token = _request_token.get("").strip()
    if not token:
        raise PermissionError("Not authenticated: connect this MCP server via OAuth.")
    return token


def _decode_token(token: str) -> int:
    """user_id from a valid MCP access token bound to the current tenant, else PermissionError."""
    from apps.accounts.authentication import MCP_TENANT_CLAIM
    from apps.mcp_server.tenant_context import current_tenant

    try:
        payload = AccessToken(token)
        user_id = int(payload["user_id"])
        token_tenant = payload.get(MCP_TENANT_CLAIM)
    except (TokenError, KeyError, ValueError) as exc:
        raise PermissionError(f"Invalid or expired token: {exc}") from exc
    if token_tenant is None or int(token_tenant) != current_tenant().id:
        raise PermissionError("Token is not valid for this company")
    return user_id
```

- [ ] **Step 7: `http/service_key.py`**

```python
def _mint_service_access_token(service_user, tenant_id: int) -> str:
    """Short-lived AccessToken for a service_user, tagged svc=True and bound to tenant_id.

    Access-token only (no RefreshToken/OutstandingToken row) — safe to call
    on every request without growing the simplejwt blacklist table.
    """
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.authentication import MCP_TENANT_CLAIM

    token = AccessToken.for_user(service_user)
    token["svc"] = True
    token[MCP_TENANT_CLAIM] = int(tenant_id)
    return str(token)
```
В `middleware` после `if credential is None: ...` вставить:
```python
        from apps.mcp_server.tenant_context import current_tenant

        tenant = current_tenant()
        bound = await sync_to_async(
            lambda: credential.tenants.filter(pk=tenant.id).exists(), thread_sensitive=True
        )()
        if not bound:
            await _reject(send, "Invalid or inactive service key")
            return
```
и заменить `token = _mint_service_access_token(service_user)` на `token = _mint_service_access_token(service_user, tenant.id)`.

- [ ] **Step 8: Запустить тесты**

Run: `git add -A && git commit -m "feat(mcp): tenant-bound JWTs; portal rejects MCP tokens; service keys per tenant host" && make push && gh pr checks <PR> --watch`
Expected: PASS. Если падают другие тесты `apps/mcp_server/tests.py`, которые вызывают `require_*` без привязанного тенанта (`McpInvestmentsBudgetsToolsTests` и др. патчат `require_module_access` — не затронуты), — добавить `_bind_tenant` и токен с claim по образцу `ServiceKeyEndToEndTests`.

---

## Task 4: OAuth-поток на хосте тенанта (authorize, вход, код, refresh)

**Files:**
- Modify: `backend_v2/apps/mcp_server/oauth/models.py` (поле `tenant`)
- Create: `backend_v2/apps/mcp_server/oauth/migrations/0003_oauthauthorizationcode_tenant.py`
- Modify: `backend_v2/apps/mcp_server/oauth/provider.py`
- Modify: `backend_v2/apps/mcp_server/oauth/views.py`
- Modify: `backend_v2/config/urls.py` (`oauth/login/` → `mcp/login/`)
- Modify: `backend_v2/apps/mcp_server/oauth/metadata.py` (удалить `mcp_oauth_login_url`)
- Test: `backend_v2/apps/mcp_server/tests.py` (новые `McpOAuthProviderTenantTests`, `McpTenantLoginViewTests`; обновить `McpOAuthLongStateTest`)

**Interfaces:**
- Consumes: Task 1 (`current_tenant`, `McpTenant.base_url`), Task 3 (`mcp_jwt_pair_for_user(user, tenant_id)`, `MCP_TENANT_CLAIM`).
- Produces:
  - `create_authorization_code(*, client_id, user_id, tenant_id, redirect_uri, redirect_uri_provided_explicitly, code_challenge, code_challenge_method, scopes, state) -> str`
  - Django URL name `mcp_oauth_login` → `/mcp/login/`
  - `KolbergAuthCode.tenant_id: int | None`, `KolbergRefreshToken.tenant_id: int | None`

- [ ] **Step 1: Написать падающие тесты**

```python
@override_settings(MCP_HTTP_ENABLED=True, BASE_DOMAIN="kolberg.uz")
class McpOAuthProviderTenantTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.mcp_server.oauth.models import OAuthClient
        from apps.tenants.models import Tenant

        self.user = get_user_model().objects.create_user(username="prov-user")
        self.a = Tenant.objects.create(name="A", subdomain="prov-a", is_active=True, mcp_enabled=True)
        self.b = Tenant.objects.create(name="B", subdomain="prov-b", is_active=True, mcp_enabled=True)
        OAuthClient.objects.create(
            client_id="c1", redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
            grant_types=["authorization_code", "refresh_token"], response_types=["code"],
        )

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def _client(self):
        from mcp.shared.auth import OAuthClientInformationFull

        return OAuthClientInformationFull(client_id="c1", redirect_uris=["https://claude.ai/api/mcp/auth_callback"])

    def _params(self, resource=None):
        from mcp.server.auth.provider import AuthorizationParams

        return AuthorizationParams(
            state="st", scopes=["mcp"], code_challenge="A" * 43,
            redirect_uri="https://claude.ai/api/mcp/auth_callback",
            redirect_uri_provided_explicitly=True, resource=resource,
        )

    def _code_for(self, tenant):
        from apps.mcp_server.oauth.provider import create_authorization_code

        return create_authorization_code(
            client_id="c1", user_id=self.user.id, tenant_id=tenant.id,
            redirect_uri="https://claude.ai/api/mcp/auth_callback", redirect_uri_provided_explicitly=True,
            code_challenge="A" * 43, code_challenge_method="S256", scopes=["mcp"], state="st",
        )

    def test_authorize_redirects_to_tenant_login_with_tenant_in_params(self):
        from asgiref.sync import async_to_sync
        from django.core import signing
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        url = async_to_sync(KolbergOAuthProvider().authorize)(self._client(), self._params())
        self.assertTrue(url.startswith("https://prov-a.kolberg.uz/mcp/login/?t="), url)
        params = signing.loads(url.split("t=", 1)[1], salt="mcp-oauth-authorize")
        self.assertEqual(params["tenant_id"], self.a.id)

    def test_authorize_rejects_foreign_resource(self):
        from asgiref.sync import async_to_sync
        from mcp.server.auth.provider import AuthorizeError
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        with self.assertRaises(AuthorizeError):
            async_to_sync(KolbergOAuthProvider().authorize)(self._client(), self._params("https://prov-b.kolberg.uz/mcp"))

    def test_authorize_accepts_resource_with_trailing_slash(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        url = async_to_sync(KolbergOAuthProvider().authorize)(self._client(), self._params("https://prov-a.kolberg.uz/mcp/"))
        self.assertIn("/mcp/login/", url)

    def test_code_of_tenant_a_not_loadable_on_host_b(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        code = self._code_for(self.a)
        _bind_tenant(self.b)
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_authorization_code)(self._client(), code))

    def test_exchange_issues_tenant_bound_tokens(self):
        from asgiref.sync import async_to_sync
        from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        provider = KolbergOAuthProvider()
        code = self._code_for(self.a)
        _bind_tenant(self.a)
        loaded = async_to_sync(provider.load_authorization_code)(self._client(), code)
        token = async_to_sync(provider.exchange_authorization_code)(self._client(), loaded)
        self.assertEqual(AccessToken(token.access_token)["mcp_tenant_id"], self.a.id)
        self.assertEqual(RefreshToken(token.refresh_token)["mcp_tenant_id"], self.a.id)

    def test_refresh_of_tenant_a_rejected_on_host_b(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider
        from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user

        refresh, _ = mcp_jwt_pair_for_user(self.user, self.a.id)
        _bind_tenant(self.b)
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_refresh_token)(self._client(), str(refresh)))

    def test_refresh_without_claim_rejected(self):
        from asgiref.sync import async_to_sync
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        legacy = str(RefreshToken.for_user(self.user))
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_refresh_token)(self._client(), legacy))

    def test_access_token_of_other_tenant_not_loaded(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        token = _mcp_access_token(self.user, self.a.id)
        _bind_tenant(self.b)
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_access_token)(token))


@override_settings(MCP_HTTP_ENABLED=True, BASE_DOMAIN="kolberg.uz", ALLOWED_HOSTS=["login-a.kolberg.uz", "login-b.kolberg.uz"])
class McpTenantLoginViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.mcp_server.oauth.models import OAuthClient
        from apps.tenants.models import Tenant, TenantMembership

        self.a = Tenant.objects.create(name="A", subdomain="login-a", is_active=True, mcp_enabled=True)
        self.b = Tenant.objects.create(name="B", subdomain="login-b", is_active=True, mcp_enabled=True)
        self.alice = get_user_model().objects.create_user(username="alice", password="x")
        TenantMembership.objects.create(user=self.alice, tenant=self.a, is_active=True)
        OAuthClient.objects.create(client_id="c1", redirect_uris=["https://claude.ai/cb"])

    def _t(self, tenant_id):
        from django.core import signing

        return signing.dumps(
            {"client_id": "c1", "redirect_uri": "https://claude.ai/cb", "redirect_uri_provided_explicitly": True,
             "code_challenge": "A" * 43, "state": "st", "scopes": ["mcp"], "tenant_id": tenant_id},
            salt="mcp-oauth-authorize",
        )

    def test_old_login_url_is_gone(self):
        self.assertEqual(self.client.get("/oauth/login/", HTTP_HOST="login-a.kolberg.uz").status_code, 404)

    def test_login_page_renders_on_tenant_host(self):
        r = self.client.get(f"/mcp/login/?t={self._t(self.a.id)}", HTTP_HOST="login-a.kolberg.uz")
        self.assertEqual(r.status_code, 200)

    def test_params_for_other_tenant_rejected(self):
        r = self.client.get(f"/mcp/login/?t={self._t(self.b.id)}", HTTP_HOST="login-a.kolberg.uz")
        self.assertEqual(r.status_code, 400)

    @patch("apps.accounts.otp.send_otp")
    def test_username_step_sends_otp_via_tenant(self, mock_send):
        r = self.client.post(
            "/mcp/login/", {"t": self._t(self.a.id), "step": "username", "username": "alice"},
            HTTP_HOST="login-a.kolberg.uz",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(mock_send.call_args.kwargs["tenant"].id, self.a.id)

    @patch("apps.accounts.otp.send_otp")
    def test_non_member_cannot_log_in(self, mock_send):
        r = self.client.post(
            "/mcp/login/", {"t": self._t(self.b.id), "step": "username", "username": "alice"},
            HTTP_HOST="login-b.kolberg.uz",
        )
        self.assertContains(r, "Нет доступа к этой компании")
        mock_send.assert_not_called()

    @patch("apps.accounts.otp.verify_otp")
    def test_otp_step_creates_code_bound_to_tenant(self, mock_verify):
        from apps.mcp_server.oauth.models import OAuthAuthorizationCode

        r = self.client.post(
            "/mcp/login/", {"t": self._t(self.a.id), "step": "otp", "username": "alice", "otp": "123456"},
            HTTP_HOST="login-a.kolberg.uz",
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(mock_verify.call_args.kwargs["tenant"].id, self.a.id)
        self.assertEqual(OAuthAuthorizationCode.objects.get().tenant_id, self.a.id)
```
`McpOAuthLongStateTest`: убрать `override_settings` с `MCP_BASE_URL`/`MCP_OAUTH_LOGIN_URL`/`_MCP_TEST_HOST`; в `setUp` создать тенант `Tenant.objects.create(name="LS", subdomain="longstate", is_active=True, mcp_enabled=True)`; в вызов `create_authorization_code` добавить `tenant_id=self.tenant.id`.

- [ ] **Step 2: Запустить — ожидается падение**

Run: `git add -A && git commit -m "test(mcp): tenant-bound OAuth flow" && make push && gh pr checks <PR> --watch`
Expected: FAIL — `create_authorization_code() got an unexpected keyword argument 'tenant_id'`.

- [ ] **Step 3: Модель и миграция**

`oauth/models.py`, в `OAuthAuthorizationCode` после `user`:
```python
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="mcp_oauth_codes",
    )
```
`oauth/migrations/0003_oauthauthorizationcode_tenant.py`:
```python
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mcp_oauth", "0002_alter_oauthauthorizationcode_state_code_challenge"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthauthorizationcode",
            name="tenant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mcp_oauth_codes",
                to="tenants.tenant",
            ),
        ),
    ]
```
Перед коммитом проверить последнюю миграцию `tenants` в `main`: `ls backend_v2/apps/tenants/migrations | sort | tail -1` — если не `0026_…`, подставить её.

- [ ] **Step 4: `provider.py`**

Импорты: убрать `from apps.mcp_server.oauth.metadata import mcp_oauth_login_url`; добавить `AuthorizeError` в импорт из `mcp.server.auth.provider`.

Модели токенов:
```python
class KolbergAuthCode(AuthorizationCode):
    user_id: int
    tenant_id: int | None = None


class KolbergRefreshToken(RefreshToken):
    user_id: int
    tenant_id: int | None = None
```
`authorize`:
```python
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Redirect user to the tenant's OTP login page with signed OAuth params."""
        from apps.mcp_server.tenant_context import current_tenant

        tenant = current_tenant()
        if params.resource and params.resource.rstrip("/") != tenant.base_url:
            raise AuthorizeError(
                error="invalid_request",
                error_description="resource does not match this MCP server",
            )
        payload = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "state": params.state or "",
            "scopes": params.scopes or [],
            "tenant_id": tenant.id,
        }
        signed = signing.dumps(payload, salt=_SIGN_SALT, compress=True)
        return f"{tenant.base_url}/login/?t={signed}"
```
`load_authorization_code`: после проверки `expires_at` добавить
```python
        from apps.mcp_server.tenant_context import current_tenant

        if record.tenant_id != current_tenant().id:
            return None
```
и в `KolbergAuthCode(...)` добавить `tenant_id=record.tenant_id`.

`exchange_authorization_code`: `refresh, access = mcp_jwt_pair_for_user(user, authorization_code.tenant_id)`.

`load_refresh_token`:
```python
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> KolbergRefreshToken | None:
        from rest_framework_simplejwt.tokens import RefreshToken as JwtRefresh
        from rest_framework_simplejwt.exceptions import TokenError as JwtTokenError

        from apps.accounts.authentication import MCP_TENANT_CLAIM
        from apps.mcp_server.tenant_context import current_tenant

        try:
            token = JwtRefresh(refresh_token)
            token_tenant = token.get(MCP_TENANT_CLAIM)
            if token_tenant is None or int(token_tenant) != current_tenant().id:
                return None
            return KolbergRefreshToken(
                token=refresh_token,
                client_id=client.client_id,
                scopes=["mcp"],
                user_id=int(token["user_id"]),
                tenant_id=int(token_tenant),
            )
        except (JwtTokenError, KeyError, ValueError):
            return None
```
`exchange_refresh_token`: `new_refresh, access = mcp_jwt_pair_for_user(user, refresh_token.tenant_id)`.

`load_access_token` не меняется (`_decode_token` из Task 3 уже сверяет тенант).

`create_authorization_code` — сделать аргументы keyword-only и добавить `tenant_id`:
```python
def create_authorization_code(
    *,
    client_id: str,
    user_id: int,
    tenant_id: int,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    code_challenge: str,
    code_challenge_method: str,
    scopes: list[str],
    state: str,
) -> str:
```
и `tenant_id=tenant_id` в `OAuthAuthorizationCode.objects.create(...)`. Обновить docstring модуля: шаг 1 — «редирект на https://<tenant>/mcp/login/?t=…».

- [ ] **Step 5: `oauth/views.py`**

Docstring: `URL: https://<tenant>.<BASE_DOMAIN>/mcp/login/?t=<signed_params>`.
`dispatch`:
```python
    def dispatch(self, request, *args, **kwargs):
        tenant = getattr(request, "tenant", None)
        if not mcp_http_enabled() or tenant is None or not tenant.mcp_enabled:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)
```
Проверка параметров — вынести в метод и использовать в `get` и `post` вместо `_decode_params(t)`:
```python
    def _params_for_tenant(self, request, t: str) -> dict | None:
        params = _decode_params(t)
        if not params or params.get("tenant_id") != request.tenant.id:
            return None
        return params
```
Хелпер членства:
```python
def _is_member(user, tenant) -> bool:
    from apps.tenants.models import TenantMembership

    return TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists()
```
`_handle_username`: после получения `user`:
```python
        if not _is_member(user, request.tenant):
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Нет доступа к этой компании."
            })
```
и `send_otp(user=user, tenant=request.tenant, ip=ip)`.
`_handle_otp`: после получения `user` та же проверка членства; `verify_otp(user=user, code=otp_code, tenant=request.tenant)`; в `create_authorization_code(...)` добавить `tenant_id=request.tenant.id`.

- [ ] **Step 6: URL и metadata**

`config/urls.py`: `path("oauth/login/", ...)` → `path("mcp/login/", McpLoginView.as_view(), name="mcp_oauth_login")`.
`oauth/metadata.py`: удалить `mcp_oauth_login_url` и `from django.conf import settings`.

- [ ] **Step 7: Запустить тесты**

Run: `git add -A && git commit -m "feat(mcp): tenant-bound OAuth authorize, login, code and refresh" && make push && gh pr checks <PR> --watch`
Expected: PASS.

---

## Task 5: Декларация доступа, инструменты без `tenant_id`, фильтрация

**Files:**
- Create: `backend_v2/apps/mcp_server/access.py`
- Modify (переписать): `backend_v2/apps/mcp_server/django_tools.py`
- Modify: `backend_v2/apps/mcp_server/server.py` (инструкции, подкласс сервера, декораторы 39 инструментов, `get_current_tenant`, docstring'и)
- Modify: `backend_v2/apps/mcp_server/tools/tenant_config.py` (удалить `list_my_tenants`)
- Test: `backend_v2/apps/mcp_server/tests.py` (удалить `McpToolDocstringRolesTests`; новые `McpToolAccessRegistryTests`, `McpToolFilteringTests`, `DjangoMcpToolDecoratorTenantTests`)

**Interfaces:**
- Consumes: Task 1 (`current_tenant`), Task 3 (`_get_token`, `_decode_token`, `set_request_token`, `mcp_jwt_pair_for_user`).
- Produces:
  - `Access` (frozen dataclass: `kind: str`, `module_key: str | None`, `require_admin_or_director: bool`), конструкторы `Access.always()`, `Access.module(key, *, admin_or_director=False)`, `Access.admin()`, `Access.admin_or_director()`; метод `allows(roles: set[str], enabled_modules: set[str]) -> bool`
  - `visible_tools(registry: dict[str, Access], *, user_id: int, tenant_id: int) -> set[str]`
  - `django_tools.TOOL_ACCESS: dict[str, Access]`, `django_mcp_tool(mcp)` → `tool(*, access: Access)`
  - `server.TenantScopedMCPServer(MCPServer)`, `server.mcp` — его экземпляр

- [ ] **Step 1: Написать падающие тесты**

Удалить класс `McpToolDocstringRolesTests`. Добавить:
```python
EXPECTED_TOOL_ACCESS = {
    "get_current_tenant": ("always", None, False),
    "get_my_role": ("always", None, False),
    "list_my_modules": ("always", None, False),
    "list_requests": ("module", "requests", False),
    "get_request": ("module", "requests", False),
    "list_request_categories": ("module", "requests", False),
    "list_cash_expenses": ("module", "cash", False),
    "list_cash_revenues": ("module", "cash", False),
    "list_bank_expenses": ("module", "bank", False),
    "list_bank_revenues": ("module", "bank", False),
    "list_card_expenses": ("module", "corporate_card", False),
    "list_card_revenues": ("module", "corporate_card", False),
    "get_pnl_report": ("module", "reports", False),
    "get_cashflow_report": ("module", "reports", False),
    "list_payroll_documents": ("module", "payroll", False),
    "get_payroll_document": ("module", "payroll", False),
    "get_investment_form_config": ("module", "investments", False),
    "list_invest_companies": ("module", "investments", False),
    "list_invest_returns": ("module", "investments", False),
    "list_project_investments": ("module", "investments", False),
    "list_invest_payout_schedule": ("module", "investments", False),
    "list_budgets": ("module", "budgets", False),
    "get_budget": ("module", "budgets", False),
    "list_budget_spend_requests": ("module", "budgets", False),
    "list_my_tasks": ("module", "tasks", False),
    "get_task": ("module", "tasks", False),
    "update_task_status": ("module", "tasks", False),
    "add_task_comment": ("module", "tasks", False),
    "edit_task": ("module", "tasks", False),
    "delete_task": ("module", "tasks", False),
    "list_assignee_candidates": ("module", "tasks", False),
    "create_task": ("module", "tasks", True),
    "list_vendors": ("module", "vendors", False),
    "list_wallets": ("module", "wallets", False),
    "list_active_users": ("admin_or_director", None, False),
    "get_tenant_info": ("admin_or_director", None, False),
    "list_module_configs": ("admin_or_director", None, False),
    "list_user_roles": ("admin", None, False),
    "list_memberships": ("admin", None, False),
}


class McpToolAccessRegistryTests(TestCase):
    """The access map is what list_tools filters by; it must match the spec table
    and the module each tools/*.py function checks with require_module_access."""

    def test_registry_matches_spec_table(self):
        from apps.mcp_server import server  # noqa: F401 — registers tools
        from apps.mcp_server.django_tools import TOOL_ACCESS

        actual = {n: (a.kind, a.module_key, a.require_admin_or_director) for n, a in TOOL_ACCESS.items()}
        self.assertEqual(actual, EXPECTED_TOOL_ACCESS)

    def test_no_tool_exposes_tenant_id_or_stale_text(self):
        from apps.mcp_server.server import mcp

        tools = mcp._tool_manager.list_tools()
        self.assertEqual(len(tools), len(EXPECTED_TOOL_ACCESS))
        for info in tools:
            with self.subTest(tool=info.name):
                self.assertNotIn("tenant_id", info.parameters.get("properties", {}))
                for stale in ("tenant_id", "list_my_tenants", "Required roles"):
                    self.assertNotIn(stale, info.description or "")


class DjangoMcpToolDecoratorTenantTests(TestCase):
    def test_tenant_id_is_hidden_and_injected(self):
        from asgiref.sync import async_to_sync
        from mcp.server.mcpserver import MCPServer
        from apps.mcp_server.access import Access
        from apps.mcp_server.django_tools import django_mcp_tool
        from apps.mcp_server.tenant_context import McpTenant, reset_current_tenant, set_current_tenant

        test_mcp = MCPServer(name="t")
        tool = django_mcp_tool(test_mcp)

        @tool(access=Access.always())
        def echo_tenant(tenant_id: int, word: str = "x") -> dict:
            """Echo."""
            return {"tenant_id": tenant_id, "word": word}

        from apps.mcp_server.django_tools import TOOL_ACCESS

        try:
            info = test_mcp._tool_manager.list_tools()[0]
            self.assertEqual(set(info.parameters["properties"]), {"word"})

            token = set_current_tenant(McpTenant(id=42, subdomain="s", name="S"))
            try:
                result = async_to_sync(test_mcp.call_tool)("echo_tenant", {"word": "hi"})
            finally:
                reset_current_tenant(token)
        finally:
            TOOL_ACCESS.pop("echo_tenant", None)  # keep the global registry equal to the spec table
        text = "".join(getattr(c, "text", "") for c in result.content)
        self.assertIn("42", text)
        self.assertIn("hi", text)


class McpToolFilteringTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig

        self.tenant = Tenant.objects.create(name="F", subdomain="filt", is_active=True, mcp_enabled=True)
        for key in ("requests", "vendors", "tasks", "cash", "reports", "investments", "payroll"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)
        self.User = get_user_model()
        self.Membership = TenantMembership

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def _user_with(self, *roles, member=True):
        from apps.tenants.models import TenantUserRole

        user = self.User.objects.create_user(username=f"u-{'-'.join(roles) or 'none'}-{member}")
        if member:
            self.Membership.objects.create(user=user, tenant=self.tenant, is_active=True)
        for role in roles:
            TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def _visible(self, user):
        from apps.mcp_server.access import visible_tools
        from apps.mcp_server.django_tools import TOOL_ACCESS
        from apps.mcp_server import server  # noqa: F401

        return visible_tools(TOOL_ACCESS, user_id=user.id, tenant_id=self.tenant.id)

    def test_requester_sees_requests_vendors_tasks_only(self):
        v = self._visible(self._user_with("requester"))
        self.assertIn("list_requests", v)
        self.assertIn("list_vendors", v)
        self.assertIn("list_my_tasks", v)
        self.assertNotIn("create_task", v)
        self.assertNotIn("list_cash_expenses", v)
        self.assertNotIn("get_pnl_report", v)
        self.assertNotIn("list_user_roles", v)

    def test_investor_sees_investments_and_reports(self):
        v = self._visible(self._user_with("investor"))
        self.assertIn("list_invest_returns", v)
        self.assertIn("get_pnl_report", v)
        self.assertNotIn("list_requests", v)
        self.assertNotIn("list_my_tasks", v)

    def test_disabled_module_hides_tools_even_for_admin(self):
        v = self._visible(self._user_with("admin"))
        self.assertIn("list_user_roles", v)
        self.assertIn("create_task", v)
        self.assertNotIn("list_budgets", v)  # budgets not enabled
        self.assertNotIn("list_bank_expenses", v)  # bank not enabled

    def test_non_member_sees_nothing(self):
        self.assertEqual(self._visible(self._user_with("admin", member=False)), set())

    def test_hidden_tool_call_is_unknown_tool(self):
        from asgiref.sync import async_to_sync
        from mcp.server.mcpserver.exceptions import ToolError
        from apps.mcp_server.auth import set_request_token
        from apps.mcp_server.server import mcp

        user = self._user_with("requester")
        _bind_tenant(self.tenant)
        set_request_token(_mcp_access_token(user, self.tenant.id))
        with self.assertRaisesRegex(ToolError, "^Unknown tool: list_payroll_documents$"):
            async_to_sync(mcp.call_tool)("list_payroll_documents", {})

    def test_list_tools_is_filtered(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.auth import set_request_token
        from apps.mcp_server.server import mcp

        user = self._user_with("requester")
        _bind_tenant(self.tenant)
        set_request_token(_mcp_access_token(user, self.tenant.id))
        names = {t.name for t in async_to_sync(mcp.list_tools)()}
        self.assertIn("get_current_tenant", names)
        self.assertIn("list_requests", names)
        self.assertNotIn("list_payroll_documents", names)
```

- [ ] **Step 2: Запустить — ожидается падение**

Run: `git add -A && git commit -m "test(mcp): tool access map, tenant injection, filtering" && make push && gh pr checks <PR> --watch`
Expected: FAIL — `No module named 'apps.mcp_server.access'`.

- [ ] **Step 3: `access.py`**

```python
"""Who may see and call an MCP tool: module + role rules, evaluated per request."""

from __future__ import annotations

from dataclasses import dataclass

from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import ROLE_MODULE_ACCESS

_ADMIN_OR_DIRECTOR = frozenset({TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR})


@dataclass(frozen=True)
class Access:
    kind: str  # "always" | "module" | "admin" | "admin_or_director"
    module_key: str | None = None
    require_admin_or_director: bool = False

    @classmethod
    def always(cls) -> "Access":
        return cls("always")

    @classmethod
    def module(cls, key: str, *, admin_or_director: bool = False) -> "Access":
        return cls("module", key, admin_or_director)

    @classmethod
    def admin(cls) -> "Access":
        return cls("admin")

    @classmethod
    def admin_or_director(cls) -> "Access":
        return cls("admin_or_director")

    def allows(self, roles: set[str], enabled_modules: set[str]) -> bool:
        if self.kind == "always":
            return True
        if self.kind == "admin":
            return TenantUserRole.ROLE_ADMIN in roles
        if self.kind == "admin_or_director":
            return bool(roles & _ADMIN_OR_DIRECTOR)
        if self.module_key not in enabled_modules:
            return False
        if not roles & ROLE_MODULE_ACCESS.get(self.module_key, set()):
            return False
        return not self.require_admin_or_director or bool(roles & _ADMIN_OR_DIRECTOR)


def visible_tools(registry: dict[str, Access], *, user_id: int, tenant_id: int) -> set[str]:
    """Names of tools the user may use in the tenant; empty for non-members."""
    from apps.tenants.models import TenantMembership, TenantModuleConfig

    if not TenantMembership.objects.filter(user_id=user_id, tenant_id=tenant_id, is_active=True).exists():
        return set()
    roles = set(
        TenantUserRole.objects.filter(user_id=user_id, tenant_id=tenant_id).values_list("role", flat=True)
    )
    modules = set(
        TenantModuleConfig.objects.filter(tenant_id=tenant_id, is_enabled=True).values_list("module_key", flat=True)
    )
    return {name for name, access in registry.items() if access.allows(roles, modules)}
```

- [ ] **Step 4: `django_tools.py`**

```python
"""
Register sync Django ORM callables as MCP tools bound to the request's tenant.

- Runs the handler via sync_to_async (thread_sensitive=True keeps request
  contextvars: JWT and tenant) — bare ORM raises SynchronousOnlyOperation in ASGI.
- A `tenant_id` parameter is removed from the tool schema and filled from the
  tenant resolved from the Host subdomain (apps.mcp_server.tenant_context).
- The tool's Access rule is recorded in TOOL_ACCESS for list_tools filtering.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from asgiref.sync import sync_to_async

from apps.mcp_server.access import Access

F = TypeVar("F", bound=Callable)

TOOL_ACCESS: dict[str, Access] = {}


def django_mcp_tool(mcp) -> Callable[..., Callable[[F], F]]:
    def tool(*, access: Access) -> Callable[[F], F]:
        def decorator(fn: F) -> F:
            sig = inspect.signature(fn)
            takes_tenant = "tenant_id" in sig.parameters
            public_params = [p for p in sig.parameters.values() if p.name != "tenant_id"]

            @wraps(fn)
            async def async_wrapper(**kwargs):
                if takes_tenant:
                    from apps.mcp_server.tenant_context import current_tenant

                    kwargs["tenant_id"] = current_tenant().id
                return await sync_to_async(fn, thread_sensitive=True)(**kwargs)

            async_wrapper.__signature__ = sig.replace(parameters=public_params)
            async_wrapper.__annotations__ = {
                k: v for k, v in getattr(fn, "__annotations__", {}).items() if k != "tenant_id"
            }
            mcp.tool()(async_wrapper)
            TOOL_ACCESS[fn.__name__] = access
            return fn

        return decorator

    return tool
```

- [ ] **Step 5: `server.py` — сервер с фильтрацией и инструкции**

Docstring модуля:
```python
"""
Kolberg MCP Server — one company (tenant) per connector.

Served over streamable HTTP at https://<tenant>.<BASE_DOMAIN>/mcp
(see apps/mcp_server/http/app.py and config/asgi.py). The tenant comes from the
Host subdomain; tools never take tenant_id. list_tools/call_tool expose only
tools allowed by the tenant's enabled modules and the user's roles.
"""
```
Убрать `_bootstrap_django()` и `import os` (сервер больше не запускается вне Django), импортировать:
```python
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from apps.mcp_server.access import Access
from apps.mcp_server.django_tools import TOOL_ACCESS, django_mcp_tool
from apps.mcp_server.tenant_context import current_tenant
```
Перед `mcp = ...` добавить:
```python
def _visible_tool_names_sync() -> set[str]:
    from apps.mcp_server.access import visible_tools
    from apps.mcp_server.auth import _decode_token, _get_token

    try:
        user_id = _decode_token(_get_token())
    except PermissionError:
        return set()
    return visible_tools(TOOL_ACCESS, user_id=user_id, tenant_id=current_tenant().id)


class TenantScopedMCPServer(MCPServer):
    """Hides tools the caller may not use; a hidden tool behaves as nonexistent."""

    async def _visible(self) -> set[str]:
        from asgiref.sync import sync_to_async

        return await sync_to_async(_visible_tool_names_sync, thread_sensitive=True)()

    async def list_tools(self):
        visible = await self._visible()
        return [t for t in await super().list_tools() if t.name in visible]

    async def call_tool(self, name, arguments, context=None):
        if name not in await self._visible():
            raise ToolError(f"Unknown tool: {name}")
        return await super().call_tool(name, arguments, context)
```
`mcp = MCPServer(` → `mcp = TenantScopedMCPServer(`; `instructions=` заменить на:
```python
    instructions="""
Kolberg is a financial management platform. This connector is bound to ONE
company (tenant); every tool works on that company only — call
get_current_tenant() to see which one. You only see the tools the current user
may use (enabled modules × roles). Everything is read-only except the tasks
tools (create_task, update_task_status, add_task_comment, edit_task, delete_task).

════════════════════════════════════════════════════════════
CRITICAL: SOURCE OF TRUTH FOR EXPENSES
════════════════════════════════════════════════════════════
ALL expenses in Kolberg are recorded as payment REQUESTS (заявки).
Cash and bank transaction records (list_cash_expenses, list_bank_expenses,
list_card_expenses) are raw accounting feeds used ONLY to reconcile whether
every expense has a matching request. They are NOT the source of truth.

DEFAULT BEHAVIOUR — always follow this:
  • When the user asks about expenses, spending, payments, or costs
    → use list_requests / get_request as the primary source.
  • Do NOT call list_cash_expenses / list_bank_expenses / list_card_expenses
    by default.

EXCEPTION — raw transaction data:
  • Only call cash/bank/card expense tools when the user EXPLICITLY asks for
    raw transaction data AND confirms they want to bypass requests.
  • Example trigger: "покажи мне сырые данные кассы" / "нужны транзакции банка
    напрямую, не через заявки".
  • When in doubt — ask the user before calling raw expense tools.

Revenues (list_cash_revenues, list_bank_revenues, list_card_revenues) are not
covered by requests and can be queried directly at any time.

════════════════════════════════════════════════════════════
ERRORS AND FILTERING
════════════════════════════════════════════════════════════
- All tools return {"error": "..."} or [{"error": "..."}] on failure.
  Always check for the "error" key before using results.
- Date filters: YYYY-MM-DD only.
- limit: default 50, max 200 (max 500 for list_vendors).
""",
```
(Блоки `HOW TO START A SESSION`, `TOOLS BY DOMAIN`, `ROLE PERMISSIONS` удаляются: список инструментов клиент получает из `list_tools`, права — фильтрацией.)

- [ ] **Step 6: `server.py` — `get_current_tenant` вместо `list_my_tenants`**

Удалить обёртку `list_my_tenants` целиком; на её место:
```python
@tool(access=Access.always())
def get_current_tenant() -> dict:
    """Return the company (tenant) this connector is bound to.

    Every other tool works on this company only. Returns id, name, subdomain.
    """
    tenant = current_tenant()
    return {"id": tenant.id, "name": tenant.name, "subdomain": tenant.subdomain}
```
В `tools/tenant_config.py` удалить функцию `list_my_tenants` (больше не используется).

- [ ] **Step 7: `server.py` — декораторы доступа**

Заменить каждое `@tool` над обёрткой на `@tool(access=...)` строго по таблице `EXPECTED_TOOL_ACCESS` из Step 1 (`always` → `Access.always()`; `("module", "payroll", False)` → `Access.module("payroll")`; `("module", "tasks", True)` → `Access.module("tasks", admin_or_director=True)`; `admin_or_director` → `Access.admin_or_director()`; `admin` → `Access.admin()`). Сигнатуры и тела обёрток не менять — `tenant_id` скрывает декоратор.

- [ ] **Step 8: `server.py` — очистить описания**

Выполнить в `backend_v2/apps/mcp_server/`:
```bash
python3 - <<'EOF'
import re
p = "server.py"
s = open(p).read()
s = re.sub(r"\n        tenant_id: Tenant primary key[^\n]*", "", s)
s = re.sub(r"\n    Required roles:[^\n]*(\n    \([^\n]*\))?\n\n", "\n", s)
s = s.replace(" (get from list_my_tenants)", "")
s = s.replace('\n\n    Args:\n    """', '\n    """')  # Args sections that only had tenant_id
open(p, "w").write(s)
EOF
grep -n "tenant_id\|list_my_tenants\|Required roles" server.py
```
Expected: `grep` выводит только сигнатуры (`tenant_id: int`) и вызовы `…(tenant_id=tenant_id, …)` внутри тел; в docstring'ах совпадений нет. Если в каком-то docstring осталась строка «Call after list_my_tenants()» (`get_my_role`) — заменить на «Call first to understand what actions are available.».

- [ ] **Step 9: Запустить тесты**

Run: `git add -A && git commit -m "feat(mcp): tools bound to tenant, access map and filtered list_tools" && make push && gh pr checks <PR> --watch`
Expected: PASS. `McpPayrollToolsTests`, `McpListRequestsDeletedTests`, `McpTaskErrorLanguageTests`, `McpInvestmentsBudgetsToolsTests` вызывают функции `tools/*.py` напрямую с `tenant_id` — не затронуты.

---

## Task 6: Сборка HTTP-приложения, удаление `api.kolberg.uz` и stdio, Traefik

**Files:**
- Modify: `backend_v2/apps/mcp_server/http/app.py`
- Delete: `backend_v2/apps/mcp_server/management/commands/run_mcp_server.py`
- Modify: `backend_v2/apps/mcp_server/server.py` (удалить `run()` и `if __name__ == "__main__"`)
- Modify: `backend_v2/config/settings.py:230-259` (удалить `MCP_BASE_URL`, `MCP_RESOURCE_URL`, `_mcp_public_origin`, `MCP_OAUTH_LOGIN_URL`; новый дефолт `MCP_ALLOWED_ORIGINS`)
- Modify: `docker-compose.yml` (env `MCP_BASE_URL`; роутер `django-v2-mcp` → `django-v2-tenant-mcp`)
- Modify: `.env.example:24-26` и строка `DJANGO_ALLOWED_HOSTS`
- Test: `backend_v2/apps/mcp_server/tests.py` (новый `McpDeploymentConfigTests`)

**Interfaces:**
- Consumes: Task 2 (`with_mcp_resource_metadata`), Task 3 (`with_service_key_auth`), Task 5 (`server.mcp`), Task 1 (`tenant_origin`).
- Produces: `get_mcp_asgi_app()` без статических адресов.

- [ ] **Step 1: Написать падающие тесты**

```python
class McpDeploymentConfigTests(TestCase):
    def test_static_mcp_urls_removed_from_settings(self):
        from django.conf import settings

        for name in ("MCP_BASE_URL", "MCP_RESOURCE_URL", "MCP_OAUTH_LOGIN_URL"):
            self.assertFalse(hasattr(settings, name), name)

    def test_default_allowed_origins_cover_claude_and_chatgpt(self):
        from django.conf import settings

        for origin in ("https://claude.ai", "https://claude.com", "https://chatgpt.com"):
            self.assertIn(origin, settings.MCP_ALLOWED_ORIGINS)

    def test_stdio_entry_point_removed(self):
        from django.core.management import get_commands

        self.assertNotIn("run_mcp_server", get_commands())

    def test_traefik_routes_mcp_on_tenant_hosts_only(self):
        from pathlib import Path

        compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"
        if not compose.exists():
            self.skipTest("docker-compose.yml not available (backend_v2-only checkout)")
        text = compose.read_text()
        self.assertIn("traefik.http.routers.django-v2-tenant-mcp.rule=(${TRAEFIK_BACKEND_V2_HOST_RULE})", text)
        self.assertNotIn("routers.django-v2-mcp.", text)
        self.assertNotIn("MCP_BASE_URL", text)
```

- [ ] **Step 2: Запустить — ожидается падение**

Run: `git add -A && git commit -m "test(mcp): deployment config for tenant MCP" && make push && gh pr checks <PR> --watch`
Expected: FAIL — `MCP_BASE_URL` ещё есть, `run_mcp_server` ещё есть.

- [ ] **Step 3: `http/app.py`**

```python
"""
Creates the MCP ASGI application (streamable HTTP + OAuth) shared by all tenant hosts.

config/asgi.py mounts it under /mcp/ on https://<tenant>.<BASE_DOMAIN> after
binding the tenant; paths below are relative to /mcp:
  /           → MCP protocol
  /authorize  → OAuth authorize (redirects to /mcp/login/, Django)
  /token      → OAuth token
  /register   → dynamic client registration

Per-host discovery (/.well-known/oauth-*) is served by config/asgi.py; the SDK's
issuer_url below is a placeholder used only by its internal metadata route.
Host and Origin are validated by config/asgi.py (the SDK only supports exact hosts).
"""

from __future__ import annotations

_mcp_asgi_app = None


def get_mcp_asgi_app():
    """Return the MCP ASGI app (lazy singleton)."""
    global _mcp_asgi_app
    if _mcp_asgi_app is not None:
        return _mcp_asgi_app

    from mcp.server.auth.provider import ProviderTokenVerifier
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
    from mcp.server.transport_security import TransportSecuritySettings

    from apps.mcp_server.http.middleware import with_mcp_resource_metadata
    from apps.mcp_server.http.service_key import with_service_key_auth
    from apps.mcp_server.oauth.provider import KolbergOAuthProvider
    from apps.mcp_server.server import mcp
    from apps.mcp_server.tenant_context import tenant_origin

    placeholder = f"{tenant_origin('mcp')}/mcp"
    mcp.settings.auth = AuthSettings(
        issuer_url=placeholder,  # type: ignore[arg-type]
        resource_server_url=placeholder,  # type: ignore[arg-type]
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
    )
    provider = KolbergOAuthProvider()
    mcp._auth_server_provider = provider
    mcp._token_verifier = ProviderTokenVerifier(provider)

    _mcp_asgi_app = with_mcp_resource_metadata(with_service_key_auth(
        mcp.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
    ))
    return _mcp_asgi_app
```

- [ ] **Step 4: Удалить stdio**

```bash
git rm backend_v2/apps/mcp_server/management/commands/run_mcp_server.py
```
В конце `server.py` удалить блок `# Entry point`, функцию `run()` и `if __name__ == "__main__": run()`.

- [ ] **Step 5: `settings.py`**

Заменить блок от комментария `# MCP HTTP/OAuth (api.kolberg.uz) is parked in git.` до конца `MCP_ALLOWED_ORIGINS = [...]` на:
```python
# MCP HTTP/OAuth on tenant hosts: https://<subdomain>.<BASE_DOMAIN>/mcp (docs/MCP_SERVER.md).
# Per-tenant switch: Tenant.mcp_enabled.
MCP_HTTP_ENABLED = os.getenv("MCP_HTTP_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

# Browser Origins allowed to call /mcp (requests without Origin are server-to-server and allowed).
_default_mcp_origins = "https://claude.ai,https://claude.com,https://chatgpt.com"
MCP_ALLOWED_ORIGINS = [
    o.strip()
    for o in (os.getenv("MCP_ALLOWED_ORIGINS", _default_mcp_origins) or _default_mcp_origins).split(",")
    if o.strip()
]
```

- [ ] **Step 6: `docker-compose.yml`**

В `environment` сервиса `backend_v2` удалить строку `MCP_BASE_URL: "https://${MCP_HOST:-api.kolberg.uz}/mcp"` и поправить комментарий над `MCP_HTTP_ENABLED`: `# Kolberg MCP on tenant hosts (see docs/MCP_SERVER.md): OAuth + tenant-bound service keys.`
Блок роутера заменить:
```yaml
      # MCP server (see docs/MCP_SERVER.md): https://<tenant>/mcp + per-host OAuth discovery.
      - traefik.http.routers.django-v2-tenant-mcp.rule=(${TRAEFIK_BACKEND_V2_HOST_RULE}) && (Path(`/mcp`) || PathPrefix(`/mcp/`) || PathPrefix(`/.well-known/oauth-`))
      - traefik.http.routers.django-v2-tenant-mcp.entrypoints=web,websecure
      - traefik.http.routers.django-v2-tenant-mcp.tls=true
      - traefik.http.routers.django-v2-tenant-mcp.tls.certresolver=mytlschallenge
      - traefik.http.routers.django-v2-tenant-mcp.service=django-v2
      - traefik.http.routers.django-v2-tenant-mcp.priority=1300
```

- [ ] **Step 7: `.env.example`**

Удалить строки 24-26 (`# MCP_HTTP_ENABLED and MCP_BASE_URL…`, `# MCP_HOST controls…`, `MCP_HOST=api.kolberg.uz`); в `DJANGO_ALLOWED_HOSTS=` удалить `,api.kolberg.uz`.

- [ ] **Step 8: Проверить, что ссылок не осталось**

Run: `grep -rnE "MCP_BASE_URL|MCP_RESOURCE_URL|MCP_OAUTH_LOGIN_URL|MCP_HOST[^_]|is_mcp_host|run_mcp_server|KOLBERG_JWT_TOKEN|oauth/login" backend_v2 docker-compose.yml .env.example Makefile deploy.sh | grep -v "tests.py"`
Expected: пусто.

- [ ] **Step 9: Запустить тесты**

Run: `git add -A && git commit -m "feat(mcp): serve only on tenant hosts; drop api.kolberg.uz and stdio" && make push && gh pr checks <PR> --watch`
Expected: PASS.

---

## Task 7: Документация и готовность PR

**Files:**
- Modify (переписать): `docs/MCP_SERVER.md`

- [ ] **Step 1: Переписать `docs/MCP_SERVER.md`**

Структура и содержание (писать фактами из кода; английский, как текущий документ):
1. **Overview** — одна компания на коннектор, адрес `https://<subdomain>.kolberg.uz/mcp`, 39 инструментов, запись только в задачах.
2. **Connecting** — Claude (Settings → Connectors → Add custom connector → URL) и ChatGPT (Developer mode → Connectors → Create → URL, Authentication: OAuth); вход по OTP через бота компании; нужен `Tenant.mcp_enabled` и членство.
3. **Switches** — `MCP_HTTP_ENABLED`, `Tenant.mcp_enabled`; неизвестный/выключенный тенант → 404.
4. **Authentication** — OAuth (per-host discovery, DCR, PKCE S256, `resource` check, токен с `mcp_tenant_id`, работает только на своём хосте; портал такие токены отклоняет) и `X-Service-Key` (ключ работает на хосте тенанта, к которому привязан; единый 401).
5. **Tool visibility** — таблица из `EXPECTED_TOOL_ACCESS` (Task 5); скрытый инструмент = `Unknown tool`.
6. **Tools reference** — оставить существующие разделы 7.x, убрав `tenant_id` из параметров и строки ролей, заменив `list_my_tenants` на `get_current_tenant`.
7. **Routing** — Traefik-роутер `django-v2-tenant-mcp`, ветка `config/asgi.py`, `/mcp/login/` → Django.
8. **Files** — дерево `apps/mcp_server/` (добавить `access.py`, `tenant_context.py`; убрать `management/commands/run_mcp_server.py`, `oauth/metadata_views.py`).

- [ ] **Step 2: Commit, push, снять черновик**

```bash
git add docs/MCP_SERVER.md
git commit -m "docs(mcp): tenant-scoped MCP reference

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make push
gh pr checks <PR> --watch
gh pr ready <PR>
```
Обновить описание PR: что меняется, что удаляется (`api.kolberg.uz/mcp`), миграция `mcp_oauth.0003`, порядок выкатки (сначала PR Task 0), проверка после деплоя:
```bash
curl -s https://lemonfit.kolberg.uz/.well-known/oauth-protected-resource   # resource = https://lemonfit.kolberg.uz/mcp
curl -s -o /dev/null -w "%{http_code}\n" https://lemonfit.kolberg.uz/mcp/  # 401
curl -s -o /dev/null -w "%{http_code}\n" https://api.kolberg.uz/mcp/       # не 401 от MCP
```
Мерж и `make deploy` — пользователь.
