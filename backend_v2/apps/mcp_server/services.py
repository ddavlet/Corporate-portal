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
