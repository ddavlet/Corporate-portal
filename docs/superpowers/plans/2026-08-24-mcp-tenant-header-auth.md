# MCP Service-Key Tenant Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let service integrations (n8n, other backends, AI agents) authenticate to `apps/mcp_server` with a static `X-Service-Key` header that is scoped to a fixed set of tenants and can call every tool (including admin-only ones) within them — without touching any of the 15 tool files.

**Architecture:** A new `McpServiceCredential` (DB-backed key) resolves to a real, synthetic `service_user` with an active `TenantMembership` + admin `TenantUserRole` in every tenant it's scoped to. A new ASGI middleware, wrapped around the existing FastMCP app, turns a valid `X-Service-Key` into a freshly-minted JWT `Authorization: Bearer` header (tagged with a `svc` claim) before the request reaches FastMCP's existing OAuth token verifier — so every downstream check (`require_module_access`, `require_admin_access`, role/module matrix, per-tool row-level scoping) runs completely unchanged, exactly as it would for a real human admin. The only change to existing files is a small, additive patch to `apps/mcp_server/auth.py` that collapses all tenant-access failure messages into one uniform message when the caller is a service credential (so a service key cannot distinguish "wrong tenant" from "tenant doesn't exist").

**Tech Stack:** Django 4.2+ (async ORM), `djangorestframework-simplejwt`, `mcp` Python SDK / FastMCP (already wired for HTTP+OAuth in this app), Django admin, Django `TestCase`.

**Spec:** `docs/superpowers/specs/2026-08-24-mcp-tenant-header-auth-design.md`

## Global Constraints

- No commits directly to `main`; branch `dev/mcp-tenant-header-auth` (already created in `.worktrees/slot-2`), merge only via PR.
- **Do not run tests locally** (`pytest`, `python manage.py test`, etc. are forbidden per `CLAUDE.md`). Every task below still follows TDD authoring order (test written before implementation), but there is no "run it locally" step — correctness is confirmed by GitHub Actions (`Backend Tests`) after `make push`, done once at the end (Task 9).
- Migrations only via `make makemigrations` (runs server-side, downloads the result) — never `python manage.py makemigrations` locally.
- OCP: new logic goes in new files/functions; the only edits to already-tested existing files are additive (`apps/mcp_server/auth.py`, `apps/mcp_server/admin.py`, `apps/mcp_server/http/app.py`) and must not change behavior for existing (non-service) callers.
- Read-only feature: no tool gains write capability; a service key is exactly as powerful as a tenant admin already is today.
- Error message for out-of-scope tenants in service mode is exactly: `Access denied: tenant {tenant_id} is not accessible with this key` — identical string regardless of *why* access failed (tenant missing, inactive, mcp disabled, or just not a member).
- Key format: `svc_<key_prefix>_<secret>`, prefix generated via `secrets.token_urlsafe(8)`, secret via `secrets.token_urlsafe(32)`, secret hashed with `django.contrib.auth.hashers.make_password`.
- Do not touch `apps/mcp_server/oauth/**` or any of `apps/mcp_server/tools/*.py` — those are explicitly out of scope (see spec's Non-goals).

---

## Task 1: `McpServiceCredential` model + migration

**Files:**
- Create: `backend_v2/apps/mcp_server/models.py`
- Test: `backend_v2/apps/mcp_server/tests.py` (append)

**Interfaces:**
- Produces: `apps.mcp_server.models.McpServiceCredential` with fields `key_prefix` (str, unique), `key_hash` (str), `name` (str), `service_user` (OneToOne to `settings.AUTH_USER_MODEL`), `tenants` (M2M to `apps.tenants.models.Tenant`), `is_active` (bool, default True), `created_at` (auto), `last_used_at` (nullable datetime).

- [ ] **Step 1: Write the model**

```python
# backend_v2/apps/mcp_server/models.py
from __future__ import annotations

from django.conf import settings
from django.db import models


class McpServiceCredential(models.Model):
    """A long-lived, tenant-scoped API key for non-human MCP callers.

    Resolves to a real `service_user` with an active TenantMembership and an
    admin TenantUserRole in every one of `tenants` (see
    apps/mcp_server/services.py::sync_tenant_access). That is what lets every
    existing tool and every require_module_access/require_admin_access check
    work for a service caller with zero changes to tools/*.py — the service
    caller genuinely is a tenant admin, just not a human.
    """

    key_prefix = models.CharField(max_length=16, unique=True, db_index=True)
    key_hash = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    service_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_service_credential",
    )
    tenants = models.ManyToManyField(
        "tenants.Tenant", related_name="mcp_service_credentials", blank=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_service_credential"

    def __str__(self) -> str:
        return f"{self.name} ({self.key_prefix})"
```

- [ ] **Step 2: Write the test (model shape / constraints)**

Append to `backend_v2/apps/mcp_server/tests.py`:

```python
class McpServiceCredentialModelTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="svc-model-test")

    def test_key_prefix_must_be_unique(self):
        from django.db import IntegrityError
        from apps.mcp_server.models import McpServiceCredential

        McpServiceCredential.objects.create(
            key_prefix="dup1", key_hash="x", name="A", service_user=self.user
        )
        other_user = self.user.__class__.objects.create_user(username="svc-model-test-2")
        with self.assertRaises(IntegrityError):
            McpServiceCredential.objects.create(
                key_prefix="dup1", key_hash="x", name="B", service_user=other_user
            )

    def test_str_includes_name_and_prefix(self):
        from apps.mcp_server.models import McpServiceCredential

        cred = McpServiceCredential.objects.create(
            key_prefix="strtest", key_hash="x", name="n8n prod", service_user=self.user
        )
        self.assertIn("n8n prod", str(cred))
        self.assertIn("strtest", str(cred))
```

- [ ] **Step 3: Run `make makemigrations`**

Per `CLAUDE.md`, this generates the migration server-side and downloads it locally — do **not** run `python manage.py makemigrations` directly. Confirm a new file appears under `backend_v2/apps/mcp_server/migrations/` (this will be the first migration for this app — `apps.mcp_server` is already in `INSTALLED_APPS`, see `backend_v2/config/settings.py:77`, but has had no `models.py` until now).

- [ ] **Step 4: Commit**

```bash
git add backend_v2/apps/mcp_server/models.py backend_v2/apps/mcp_server/tests.py backend_v2/apps/mcp_server/migrations/
git commit -m "feat(mcp): add McpServiceCredential model"
```

---

## Task 2: `services.py` — key generation, verification, tenant-access sync

**Files:**
- Create: `backend_v2/apps/mcp_server/services.py`
- Test: `backend_v2/apps/mcp_server/tests.py` (append)

**Interfaces:**
- Consumes: `apps.mcp_server.models.McpServiceCredential` (Task 1); `apps.tenants.models.{Tenant, TenantMembership, TenantUserRole}`.
- Produces:
  - `provision_service_credential(name: str, tenant_ids: list[int]) -> tuple[McpServiceCredential, str]` — `str` is the raw key, shown once.
  - `sync_tenant_access(credential: McpServiceCredential) -> None`.
  - `verify_service_key(raw_key: str) -> McpServiceCredential | None` — sync function (wrapped with `sync_to_async` by the middleware in Task 4, do not make this `async def` — see Task 4's note on why).

- [ ] **Step 1: Write the tests**

Append to `backend_v2/apps/mcp_server/tests.py`:

```python
class ProvisionServiceCredentialTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant

        self.tenant_a = Tenant.objects.create(name="A", subdomain="svc-a", is_active=True, mcp_enabled=True)
        self.tenant_b = Tenant.objects.create(name="B", subdomain="svc-b", is_active=True, mcp_enabled=True)

    def test_creates_service_user_with_unusable_password(self):
        from apps.mcp_server.services import provision_service_credential

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        self.assertFalse(credential.service_user.has_usable_password())

    def test_raw_key_verifies_and_hash_does_not_match_raw_secret(self):
        from apps.mcp_server.services import provision_service_credential, verify_service_key

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        self.assertNotEqual(credential.key_hash, raw_key)
        found = verify_service_key(raw_key)
        self.assertEqual(found.pk, credential.pk)

    def test_wrong_secret_does_not_verify(self):
        from apps.mcp_server.services import provision_service_credential, verify_service_key

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        prefix = raw_key.split("_")[1]
        self.assertIsNone(verify_service_key(f"svc_{prefix}_wrong-secret"))

    def test_inactive_credential_does_not_verify(self):
        from apps.mcp_server.services import provision_service_credential, verify_service_key

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        credential.is_active = False
        credential.save(update_fields=["is_active"])
        self.assertIsNone(verify_service_key(raw_key))

    def test_malformed_key_does_not_verify(self):
        from apps.mcp_server.services import verify_service_key

        self.assertIsNone(verify_service_key("not-a-service-key"))
        self.assertIsNone(verify_service_key("svc_missingsecret"))

    def test_grants_admin_membership_in_scoped_tenants_only(self):
        from apps.mcp_server.services import provision_service_credential
        from apps.tenants.models import TenantMembership, TenantUserRole

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id])
        user = credential.service_user

        self.assertTrue(
            TenantMembership.objects.filter(user=user, tenant=self.tenant_a, is_active=True).exists()
        )
        self.assertTrue(
            TenantUserRole.objects.filter(
                user=user, tenant=self.tenant_a, role=TenantUserRole.ROLE_ADMIN
            ).exists()
        )
        self.assertFalse(TenantMembership.objects.filter(user=user, tenant=self.tenant_b).exists())

    def test_sync_tenant_access_removes_stale_tenants(self):
        from apps.mcp_server.services import provision_service_credential, sync_tenant_access
        from apps.tenants.models import TenantMembership, TenantUserRole

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id, self.tenant_b.id])
        user = credential.service_user

        credential.tenants.remove(self.tenant_b)
        sync_tenant_access(credential)

        self.assertFalse(
            TenantMembership.objects.filter(user=user, tenant=self.tenant_b, is_active=True).exists()
        )
        self.assertFalse(TenantUserRole.objects.filter(user=user, tenant=self.tenant_b).exists())
        # tenant A untouched
        self.assertTrue(
            TenantMembership.objects.filter(user=user, tenant=self.tenant_a, is_active=True).exists()
        )

    def test_sync_tenant_access_adds_newly_scoped_tenants(self):
        from apps.mcp_server.services import provision_service_credential, sync_tenant_access
        from apps.tenants.models import TenantMembership

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id])
        credential.tenants.add(self.tenant_b)
        sync_tenant_access(credential)

        self.assertTrue(
            TenantMembership.objects.filter(
                user=credential.service_user, tenant=self.tenant_b, is_active=True
            ).exists()
        )
```

- [ ] **Step 2: Write the implementation**

```python
# backend_v2/apps/mcp_server/services.py
from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password


def _generate_key() -> tuple[str, str, str]:
    """Return (raw_key, key_prefix, secret) for a new service credential."""
    prefix = secrets.token_urlsafe(8)
    secret = secrets.token_urlsafe(32)
    return f"svc_{prefix}_{secret}", prefix, secret


def provision_service_credential(name: str, tenant_ids: list[int]):
    """Create a new McpServiceCredential (+ backing service_user) scoped to tenant_ids.

    Returns (credential, raw_key). raw_key is shown to the caller exactly once —
    only its hash is persisted, it cannot be recovered afterward.
    """
    from apps.mcp_server.models import McpServiceCredential
    from apps.tenants.models import Tenant

    User = get_user_model()
    raw_key, prefix, secret = _generate_key()

    service_user = User.objects.create(username=f"mcp-service-{prefix}", is_active=True)
    service_user.set_unusable_password()
    service_user.save(update_fields=["password"])

    credential = McpServiceCredential.objects.create(
        key_prefix=prefix,
        key_hash=make_password(secret),
        name=name,
        service_user=service_user,
    )
    credential.tenants.set(Tenant.objects.filter(id__in=tenant_ids))
    sync_tenant_access(credential)
    return credential, raw_key


def sync_tenant_access(credential) -> None:
    """Make TenantMembership/TenantUserRole(admin) for credential.service_user
    match credential.tenants.all() exactly: add missing, remove/deactivate stale.
    """
    from apps.tenants.models import TenantMembership, TenantUserRole

    user = credential.service_user
    tenants = list(credential.tenants.all())
    wanted_ids = {t.id for t in tenants}

    for tenant in tenants:
        membership, _ = TenantMembership.objects.get_or_create(
            user=user, tenant=tenant, defaults={"is_active": True}
        )
        if not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active"])
        TenantUserRole.objects.get_or_create(
            tenant=tenant, user=user, role=TenantUserRole.ROLE_ADMIN
        )

    stale_memberships = TenantMembership.objects.filter(user=user, is_active=True).exclude(
        tenant_id__in=wanted_ids
    )
    for membership in stale_memberships:
        membership.is_active = False
        membership.save(update_fields=["is_active"])

    TenantUserRole.objects.filter(user=user, role=TenantUserRole.ROLE_ADMIN).exclude(
        tenant_id__in=wanted_ids
    ).delete()


def verify_service_key(raw_key: str):
    """Return the matching, active McpServiceCredential for raw_key, or None.

    Sync on purpose: called from async ASGI middleware via sync_to_async
    (see apps/mcp_server/http/service_key.py) so it stays trivially unit
    testable with a plain Django TestCase, matching this app's existing
    testing pattern (see DjangoMcpToolDecoratorTests in tests.py).
    """
    from apps.mcp_server.models import McpServiceCredential

    if not raw_key.startswith("svc_"):
        return None
    body = raw_key[len("svc_"):]
    prefix, _, secret = body.partition("_")
    if not prefix or not secret:
        return None
    try:
        credential = McpServiceCredential.objects.get(key_prefix=prefix, is_active=True)
    except McpServiceCredential.DoesNotExist:
        return None
    if not check_password(secret, credential.key_hash):
        return None
    return credential
```

- [ ] **Step 3: Commit**

```bash
git add backend_v2/apps/mcp_server/services.py backend_v2/apps/mcp_server/tests.py
git commit -m "feat(mcp): add service-credential provisioning and verification"
```

---

## Task 3: `auth.py` — uniform tenant-denial message for service callers

**Files:**
- Modify: `backend_v2/apps/mcp_server/auth.py`
- Test: `backend_v2/apps/mcp_server/tests.py` (append)

**Interfaces:**
- Consumes: nothing new from earlier tasks (this task only needs `AccessToken`/`TokenError`, already imported in `auth.py`).
- Produces: `_is_service_claim(token: str) -> bool`; `_get_user_and_tenant(user_id, tenant_id, *, service_mode: bool = False)` (same public behavior as today when `service_mode=False`, the default — existing callers and existing tests are unaffected).

- [ ] **Step 1: Write the tests**

Append to `backend_v2/apps/mcp_server/tests.py`:

```python
class IsServiceClaimTests(TestCase):
    def test_true_for_token_with_svc_claim(self):
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.mcp_server.auth import _is_service_claim

        user = get_user_model().objects.create_user(username="svc-claim-test")
        token = AccessToken.for_user(user)
        token["svc"] = True
        self.assertTrue(_is_service_claim(str(token)))

    def test_false_for_ordinary_token(self):
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.mcp_server.auth import _is_service_claim

        user = get_user_model().objects.create_user(username="svc-claim-test-2")
        token = AccessToken.for_user(user)
        self.assertFalse(_is_service_claim(str(token)))

    def test_false_for_garbage_token(self):
        from apps.mcp_server.auth import _is_service_claim

        self.assertFalse(_is_service_claim("not-a-jwt"))


class ServiceModeUniformDenialTests(TestCase):
    """service_mode=True must give the exact same message for every failure
    reason, so a service key can't distinguish 'wrong tenant' from 'tenant
    doesn't exist'. service_mode=False (the default) must be untouched —
    covered already by McpTenantToggleTests."""

    def _expect_uniform_denial(self, user_id, tenant_id):
        from apps.mcp_server.auth import _get_user_and_tenant

        with self.assertRaises(PermissionError) as ctx:
            _get_user_and_tenant(user_id, tenant_id, service_mode=True)
        self.assertEqual(
            str(ctx.exception), f"Access denied: tenant {tenant_id} is not accessible with this key"
        )

    def test_nonexistent_tenant(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(username="svc-deny-1")
        self._expect_uniform_denial(user.id, 999_999)

    def test_tenant_exists_but_not_a_member(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant

        user = get_user_model().objects.create_user(username="svc-deny-2")
        tenant = Tenant.objects.create(name="X", subdomain="svc-deny-2", is_active=True, mcp_enabled=True)
        self._expect_uniform_denial(user.id, tenant.id)

    def test_tenant_exists_but_mcp_disabled(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant, TenantMembership

        user = get_user_model().objects.create_user(username="svc-deny-3")
        tenant = Tenant.objects.create(name="Y", subdomain="svc-deny-3", is_active=True, mcp_enabled=False)
        TenantMembership.objects.create(user=user, tenant=tenant, is_active=True)
        self._expect_uniform_denial(user.id, tenant.id)

    def test_two_different_denial_reasons_give_identical_message(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant
        from apps.mcp_server.auth import _get_user_and_tenant

        user = get_user_model().objects.create_user(username="svc-deny-4")
        tenant = Tenant.objects.create(name="Z", subdomain="svc-deny-4", is_active=True, mcp_enabled=True)

        with self.assertRaises(PermissionError) as ctx_a:
            _get_user_and_tenant(user.id, 999_999, service_mode=True)
        with self.assertRaises(PermissionError) as ctx_b:
            _get_user_and_tenant(user.id, tenant.id, service_mode=True)  # exists, not a member
        self.assertEqual(str(ctx_a.exception), str(ctx_b.exception))
```

- [ ] **Step 2: Write the implementation**

In `backend_v2/apps/mcp_server/auth.py`, rename the existing body of `_get_user_and_tenant` to `_get_user_and_tenant_unchecked` (verbatim, no logic changes) and add a thin wrapper plus the new claim helper:

```python
def _is_service_claim(token: str) -> bool:
    """True if `token` was minted by the service-key middleware (custom `svc` claim)."""
    try:
        return bool(AccessToken(token).payload.get("svc", False))
    except TokenError:
        return False


def _get_user_and_tenant(user_id: int, tenant_id: int, *, service_mode: bool = False):
    try:
        return _get_user_and_tenant_unchecked(user_id, tenant_id)
    except PermissionError:
        if service_mode:
            raise PermissionError(
                f"Access denied: tenant {tenant_id} is not accessible with this key"
            )
        raise


def _get_user_and_tenant_unchecked(user_id: int, tenant_id: int):
    from apps.accounts.models import User
    from apps.tenants.models import Tenant, TenantMembership

    try:
        user = User.objects.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        raise PermissionError("User not found or deactivated")

    try:
        tenant = Tenant.objects.get(id=tenant_id, is_active=True)
    except Tenant.DoesNotExist:
        raise PermissionError(f"Tenant {tenant_id} not found or inactive")

    if not tenant.mcp_enabled:
        raise PermissionError(
            f"MCP access is not enabled for tenant '{tenant.subdomain}'. "
            "Ask your administrator to enable it in tenant settings."
        )

    if not TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
        raise PermissionError("User is not an active member of this tenant")

    return user, tenant
```

Then update `require_module_access`, `require_admin_access`, `require_admin_or_director` to thread `service_mode` through (same edit in all three — get the token once, decode it, check the claim, pass it along):

```python
def require_module_access(tenant_id: int, module_key: str):
    token = _get_token()
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id, service_mode=_is_service_claim(token))

    from apps.tenants.permissions import has_effective_module_access

    if not has_effective_module_access(user=user, tenant=tenant, module_key=module_key):
        raise PermissionError(
            f"Access denied: your role does not allow access to module '{module_key}', "
            "or the module is disabled for this tenant"
        )

    return user, tenant


def require_admin_access(tenant_id: int):
    token = _get_token()
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id, service_mode=_is_service_claim(token))

    from apps.tenants.models import TenantUserRole

    if not TenantUserRole.objects.filter(
        tenant=tenant, user=user, role=TenantUserRole.ROLE_ADMIN
    ).exists():
        raise PermissionError("Admin role required for this operation")

    return user, tenant


def require_admin_or_director(tenant_id: int):
    token = _get_token()
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id, service_mode=_is_service_claim(token))

    from apps.tenants.models import TenantUserRole

    if not TenantUserRole.objects.filter(
        tenant=tenant,
        user=user,
        role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR],
    ).exists():
        raise PermissionError("Admin or Director role required for this operation")

    return user, tenant
```

Do not change `_get_token`, `_decode_token`, `set_request_token`, or the module docstring's other contracts — `_decode_token`'s return type (bare `int`) must stay exactly as-is; `oauth/provider.py::load_access_token` and the existing `McpTenantToggleTests` mocks depend on it.

- [ ] **Step 3: Commit**

```bash
git add backend_v2/apps/mcp_server/auth.py backend_v2/apps/mcp_server/tests.py
git commit -m "feat(mcp): uniform tenant-denial message for service-key callers"
```

---

## Task 4: `http/service_key.py` — ASGI middleware + token minting

**Files:**
- Create: `backend_v2/apps/mcp_server/http/service_key.py`
- Modify: `backend_v2/apps/mcp_server/http/app.py`
- Test: `backend_v2/apps/mcp_server/tests.py` (append)

**Interfaces:**
- Consumes: `apps.mcp_server.services.verify_service_key` (Task 2); `apps.mcp_server.models.McpServiceCredential` (Task 1).
- Produces: `with_service_key_auth(app) -> ASGI callable` — wraps an ASGI app; `_mint_service_access_token(service_user) -> str` (module-private, but imported directly by tests).

- [ ] **Step 1: Write the tests**

Append to `backend_v2/apps/mcp_server/tests.py`:

```python
class ServiceKeyMiddlewareTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant
        from apps.mcp_server.services import provision_service_credential

        self.tenant = Tenant.objects.create(
            name="MW", subdomain="svc-mw", is_active=True, mcp_enabled=True
        )
        self.credential, self.raw_key = provision_service_credential("mw-test", [self.tenant.id])

    @staticmethod
    def _scope(headers: list[tuple[bytes, bytes]]):
        return {"type": "http", "path": "/", "headers": headers}

    def _run(self, app, headers):
        import asyncio
        from apps.mcp_server.http.service_key import with_service_key_auth

        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        wrapped = with_service_key_auth(app)
        asyncio.run(wrapped(self._scope(headers), receive, send))
        return sent

    def test_no_header_passes_through_unchanged(self):
        seen_scopes = []

        async def downstream(scope, receive, send):
            seen_scopes.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self._run(downstream, headers=[(b"authorization", b"Bearer original")])
        self.assertEqual(seen_scopes[0]["headers"], [(b"authorization", b"Bearer original")])

    def test_valid_key_rewrites_authorization_header(self):
        from apps.mcp_server.auth import _decode_token, _is_service_claim

        seen_scopes = []

        async def downstream(scope, receive, send):
            seen_scopes.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self._run(downstream, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])

        auth_headers = [v for k, v in seen_scopes[0]["headers"] if k == b"authorization"]
        self.assertEqual(len(auth_headers), 1)
        token = auth_headers[0].decode("latin-1").removeprefix("Bearer ")
        self.assertEqual(_decode_token(token), self.credential.service_user_id)
        self.assertTrue(_is_service_claim(token))

    def test_invalid_key_returns_401_and_never_calls_downstream(self):
        downstream_called = []

        async def downstream(scope, receive, send):
            downstream_called.append(True)

        sent = self._run(downstream, headers=[(b"x-service-key", b"svc_bad_bad")])

        self.assertEqual(downstream_called, [])
        self.assertEqual(sent[0]["status"], 401)

    def test_valid_key_updates_last_used_at(self):
        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self.assertIsNone(self.credential.last_used_at)
        self._run(downstream, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])

        self.credential.refresh_from_db()
        self.assertIsNotNone(self.credential.last_used_at)

    def test_non_http_scope_passes_through(self):
        import asyncio
        from apps.mcp_server.http.service_key import with_service_key_auth

        calls = []

        async def downstream(scope, receive, send):
            calls.append(scope["type"])

        wrapped = with_service_key_auth(downstream)
        asyncio.run(wrapped({"type": "lifespan"}, None, None))
        self.assertEqual(calls, ["lifespan"])
```

- [ ] **Step 2: Write the implementation**

```python
# backend_v2/apps/mcp_server/http/service_key.py
"""
ASGI middleware: resolve an X-Service-Key header into a Bearer JWT before
FastMCP's own OAuth token verifier sees the request.

No X-Service-Key header -> pass through unchanged (normal Authorization path,
either a manually-set human JWT or one obtained through /oauth/login).
Invalid/inactive key -> 401 immediately; the wrapped app is never called
(fail-closed — no silent fallback to Authorization).
"""

from __future__ import annotations

import json

from asgiref.sync import sync_to_async

_HEADER = b"x-service-key"


async def _reject(send, message: str) -> None:
    body = json.dumps({"error": message}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _mint_service_access_token(service_user) -> str:
    """Mint a short-lived AccessToken for a service_user, tagged svc=True.

    Access-token only (no RefreshToken/OutstandingToken row) — safe to call
    on every request without growing the simplejwt blacklist table.
    """
    from rest_framework_simplejwt.tokens import AccessToken

    token = AccessToken.for_user(service_user)
    token["svc"] = True
    return str(token)


def with_service_key_auth(app):
    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_key = headers.get(_HEADER)
        if raw_key is None:
            await app(scope, receive, send)
            return

        from apps.mcp_server.services import verify_service_key

        credential = await sync_to_async(verify_service_key, thread_sensitive=True)(
            raw_key.decode("latin-1")
        )
        if credential is None:
            await _reject(send, "Invalid or inactive service key")
            return

        service_user = await sync_to_async(lambda: credential.service_user, thread_sensitive=True)()
        token = _mint_service_access_token(service_user)

        from apps.mcp_server.models import McpServiceCredential
        from django.utils import timezone

        await McpServiceCredential.objects.filter(pk=credential.pk).aupdate(
            last_used_at=timezone.now()
        )

        new_headers = [(k, v) for k, v in scope.get("headers", []) if k != b"authorization"]
        new_headers.append((b"authorization", f"Bearer {token}".encode("latin-1")))

        await app({**scope, "headers": new_headers}, receive, send)

    return middleware
```

Then wire it into `backend_v2/apps/mcp_server/http/app.py` — change the one line that builds `_mcp_asgi_app`:

```python
# before:
    _mcp_asgi_app = with_mcp_resource_metadata(mcp.streamable_http_app())

# after:
    from apps.mcp_server.http.service_key import with_service_key_auth

    _mcp_asgi_app = with_mcp_resource_metadata(with_service_key_auth(mcp.streamable_http_app()))
```

Place the `with_service_key_auth` import next to the existing `from apps.mcp_server.http.middleware import with_mcp_resource_metadata` import in that file, so the wrapping order reads top-to-bottom the same as request flow: service-key resolution runs first (rewrites the header), then the resource-metadata wrapper, then FastMCP itself.

- [ ] **Step 3: Commit**

```bash
git add backend_v2/apps/mcp_server/http/service_key.py backend_v2/apps/mcp_server/http/app.py backend_v2/apps/mcp_server/tests.py
git commit -m "feat(mcp): X-Service-Key ASGI middleware, wired into the MCP app"
```

---

## Task 5: `admin.py` — provisioning UX for `McpServiceCredential`

**Files:**
- Modify: `backend_v2/apps/mcp_server/admin.py`
- Test: `backend_v2/apps/mcp_server/tests.py` (append)

**Interfaces:**
- Consumes: `apps.mcp_server.services.{provision_service_credential, sync_tenant_access}` (Task 2).
- Produces: `McpServiceCredentialAdmin` registered for `McpServiceCredential` — on add, provisions the credential and shows the raw key once via `self.message_user(..., level=messages.WARNING)`; on any save, reconciles tenant access via `sync_tenant_access`.

- [ ] **Step 1: Write the tests**

Append to `backend_v2/apps/mcp_server/tests.py`:

```python
class McpServiceCredentialAdminTests(TestCase):
    def setUp(self):
        from django.contrib.admin.sites import AdminSite
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant
        from apps.mcp_server.admin import McpServiceCredentialAdmin
        from apps.mcp_server.models import McpServiceCredential

        self.tenant_a = Tenant.objects.create(name="AA", subdomain="admin-a", is_active=True, mcp_enabled=True)
        self.tenant_b = Tenant.objects.create(name="BB", subdomain="admin-b", is_active=True, mcp_enabled=True)
        self.admin = McpServiceCredentialAdmin(McpServiceCredential, AdminSite())
        self.staff = get_user_model().objects.create_user(username="staff", is_staff=True)

    def _fake_request(self):
        from django.test import RequestFactory

        request = RequestFactory().post("/admin/mcp_server/mcpservicecredential/add/")
        request.user = self.staff
        request._messages = _DummyMessages()
        return request

    def test_add_provisions_credential_and_messages_raw_key(self):
        from apps.mcp_server.models import McpServiceCredential

        obj = McpServiceCredential(name="n8n", is_active=True)
        form = _FakeForm(cleaned_data={"tenants": [self.tenant_a]})
        request = self._fake_request()

        self.admin.save_model(request, obj, form, change=False)

        self.assertIsNotNone(obj.pk)
        saved = McpServiceCredential.objects.get(pk=obj.pk)
        self.assertEqual(saved.name, "n8n")
        self.assertTrue(any("shown once" in m for m in request._messages.messages))

    def test_save_related_syncs_tenant_access(self):
        from apps.mcp_server.services import provision_service_credential
        from apps.tenants.models import TenantMembership

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id])
        credential.tenants.add(self.tenant_b)

        request = self._fake_request()
        form = _FakeForm(cleaned_data={}, instance=credential)
        self.admin.save_related(request, form, formsets=[], change=True)

        self.assertTrue(
            TenantMembership.objects.filter(
                user=credential.service_user, tenant=self.tenant_b, is_active=True
            ).exists()
        )


class _FakeForm:
    def __init__(self, cleaned_data, instance=None):
        self.cleaned_data = cleaned_data
        self.instance = instance
        self.save_m2m = lambda: None


class _DummyMessages:
    def __init__(self):
        self.messages = []

    def add(self, level, message, extra_tags):
        self.messages.append(message)
```

- [ ] **Step 2: Write the implementation**

```python
# backend_v2/apps/mcp_server/admin.py
from django.contrib import admin, messages

from apps.mcp_server.models import McpServiceCredential
from apps.mcp_server.services import provision_service_credential, sync_tenant_access


@admin.register(McpServiceCredential)
class McpServiceCredentialAdmin(admin.ModelAdmin):
    list_display = ("name", "key_prefix", "is_active", "created_at", "last_used_at")
    filter_horizontal = ("tenants",)
    fields = ("name", "tenants", "is_active", "key_prefix", "service_user", "created_at", "last_used_at")
    readonly_fields = ("key_prefix", "service_user", "created_at", "last_used_at")

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return

        tenant_ids = [t.id for t in form.cleaned_data.get("tenants", [])]
        credential, raw_key = provision_service_credential(name=obj.name, tenant_ids=tenant_ids)
        credential.is_active = obj.is_active
        credential.save(update_fields=["is_active"])

        # Point the admin form's in-memory instance at the row provision_service_credential
        # already created, so Django's own post-save machinery (save_related below,
        # the redirect to the change page) operates on the real, persisted object.
        obj.pk = credential.pk
        obj.key_prefix = credential.key_prefix
        obj.key_hash = credential.key_hash
        obj.service_user_id = credential.service_user_id
        obj.created_at = credential.created_at

        self.message_user(
            request,
            f"Service key (shown once, save it now): {raw_key}",
            level=messages.WARNING,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sync_tenant_access(form.instance)
```

Note the original file was just `from django.contrib import admin` with no registrations — this replaces its entire contents.

- [ ] **Step 3: Commit**

```bash
git add backend_v2/apps/mcp_server/admin.py backend_v2/apps/mcp_server/tests.py
git commit -m "feat(mcp): Django admin for McpServiceCredential"
```

---

## Task 6: End-to-end integration test

**Files:**
- Test: `backend_v2/apps/mcp_server/tests.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1-4 (no new production code in this task — this task is the acceptance check for the feature's Goals).

- [ ] **Step 1: Write the test**

Append to `backend_v2/apps/mcp_server/tests.py`:

```python
class ServiceKeyEndToEndTests(TestCase):
    """Exercises the real seam between service_key.py's minted token and
    auth.py's require_* functions — the same integration FastMCP relies on
    in production, without driving the full streamable-http/JSON-RPC stack."""

    def setUp(self):
        from apps.tenants.models import Tenant, TenantModuleConfig
        from apps.mcp_server.services import provision_service_credential

        self.tenant_a = Tenant.objects.create(name="E2E-A", subdomain="e2e-a", is_active=True, mcp_enabled=True)
        self.tenant_b = Tenant.objects.create(name="E2E-B", subdomain="e2e-b", is_active=True, mcp_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant_a, module_key="requests", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant_b, module_key="requests", is_enabled=True)

        self.credential, self.raw_key = provision_service_credential("e2e", [self.tenant_a.id])

    def _minted_token(self):
        from apps.mcp_server.http.service_key import _mint_service_access_token

        return _mint_service_access_token(self.credential.service_user)

    def test_service_token_grants_module_access_for_scoped_tenant(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        user, tenant = require_module_access(self.tenant_a.id, "requests")
        self.assertEqual(tenant.id, self.tenant_a.id)
        self.assertEqual(user.id, self.credential.service_user_id)

    def test_service_token_grants_admin_only_tools(self):
        from apps.mcp_server.auth import set_request_token, require_admin_access

        set_request_token(self._minted_token())
        user, tenant = require_admin_access(self.tenant_a.id)
        self.assertEqual(tenant.id, self.tenant_a.id)

    def test_service_token_denied_for_out_of_scope_tenant(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        with self.assertRaises(PermissionError) as ctx:
            require_module_access(self.tenant_b.id, "requests")
        self.assertEqual(
            str(ctx.exception),
            f"Access denied: tenant {self.tenant_b.id} is not accessible with this key",
        )

    def test_service_token_denied_identically_for_nonexistent_tenant(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        with self.assertRaises(PermissionError) as ctx_out_of_scope:
            require_module_access(self.tenant_b.id, "requests")
        with self.assertRaises(PermissionError) as ctx_nonexistent:
            require_module_access(999_999, "requests")
        self.assertEqual(str(ctx_out_of_scope.exception), str(ctx_nonexistent.exception))

    def test_human_jwt_path_is_completely_unaffected(self):
        """Sanity check: an ordinary human JWT still goes through the original,
        unmodified messages — service_mode branching must be a strict no-op
        for non-service tokens."""
        from django.contrib.auth import get_user_model
        from apps.tenants.models import TenantMembership
        from apps.mcp_server.auth import set_request_token, require_module_access
        from rest_framework_simplejwt.tokens import AccessToken

        human = get_user_model().objects.create_user(username="e2e-human")
        TenantMembership.objects.create(user=human, tenant=self.tenant_a, is_active=True)
        from apps.tenants.models import TenantUserRole

        TenantUserRole.objects.create(tenant=self.tenant_a, user=human, role=TenantUserRole.ROLE_REQUESTER)

        set_request_token(str(AccessToken.for_user(human)))
        user, tenant = require_module_access(self.tenant_a.id, "requests")
        self.assertEqual(user.id, human.id)

        with self.assertRaises(PermissionError) as ctx:
            require_module_access(self.tenant_b.id, "requests")
        # human path keeps the original, non-uniform message
        self.assertEqual(str(ctx.exception), "User is not an active member of this tenant")
```

- [ ] **Step 2: Commit**

```bash
git add backend_v2/apps/mcp_server/tests.py
git commit -m "test(mcp): end-to-end coverage for service-key tenant scoping"
```

---

## Task 7: Docs update

**Files:**
- Modify: `docs/MCP_SERVER.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update `docs/MCP_SERVER.md`**

In the "Production status" callout at the top, add a note that a second, tenant-scoped service-key auth mode now exists (still gated behind the same `MCP_HTTP_ENABLED` flag as the rest of HTTP/OAuth). Add a new numbered section (after "4. Authentication & security model") documenting:

```markdown
## 4a. Service-key authentication (tenant-scoped, non-human callers)

For integrations that are not a specific human user (n8n workflows, other
backends, agents), an admin can issue a service key scoped to one or more
tenants via Django admin (`McpServiceCredential`).

- Header: `X-Service-Key: svc_<prefix>_<secret>`.
- The key resolves to a real, synthetic `service_user` who is an admin
  member of exactly the tenants the key was scoped to — so it can call
  every tool (including admin-only ones: `get_integration_config`,
  `list_user_roles`, `list_memberships`) within those tenants, subject to
  the same per-tenant toggles (`Tenant.mcp_enabled`, `TenantModuleConfig`)
  a human admin would be.
- A `tenant_id` outside the key's scope — or one that doesn't exist at all —
  produces the identical error: `Access denied: tenant {id} is not
  accessible with this key`. The two cases are indistinguishable by design.
- Issuing a key shows the raw secret exactly once, in the Django admin
  success message on creation. It cannot be recovered afterward — only
  reissued.
- Revoke by unchecking "is active" on the credential in admin.
```

- [ ] **Step 2: Commit**

```bash
git add docs/MCP_SERVER.md
git commit -m "docs(mcp): document X-Service-Key tenant-scoped auth"
```

---

## Task 8: Push and confirm CI

**Files:** none.

- [ ] **Step 1: Push the branch**

```bash
cd /Users/HP/Documents/Programming/repos/kolberg-projects/kolberg/.worktrees/slot-2
make push
```

- [ ] **Step 2: Wait for and confirm GitHub Actions**

Confirm both `Backend Tests` and `Vitest` workflows pass on the pushed branch (this is where every test written in Tasks 1-6 actually gets executed for the first time — no local run happened per Global Constraints).

- [ ] **Step 3: Open the PR**

Per `CLAUDE.md`: PR into `main`, do not merge without review/approval. Do not run `make deploy` — that is a separate, explicitly user-triggered step after merge.
