"""MCP tools for tenant configuration: module flags, user roles, memberships."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_admin_access, require_admin_or_director, _get_token, _decode_token
from apps.mcp_server.utils import json_safe


def list_my_tenants() -> list[dict[str, Any]]:
    """Return all active tenants the current user is a member of.

    Call this first to discover available tenant IDs and names.
    No tenant_id required — works from the current user's token.
    """
    token = _get_token()
    user_id = _decode_token(token)

    from apps.tenants.models import TenantMembership

    memberships = (
        TenantMembership.objects
        .filter(user_id=user_id, is_active=True, tenant__is_active=True)
        .select_related("tenant")
        .order_by("tenant__name")
    )

    return [
        {
            "id": m.tenant.id,
            "name": m.tenant.name,
            "subdomain": m.tenant.subdomain,
        }
        for m in memberships
    ]


def get_my_role(tenant_id: int) -> dict[str, Any]:
    """Return the current user's roles in a tenant.

    Call this after list_my_tenants() to understand what actions are available.
    Any active tenant member can call this.
    """
    token = _get_token()
    user_id = _decode_token(token)

    from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

    try:
        tenant = Tenant.objects.get(id=tenant_id, is_active=True)
    except Tenant.DoesNotExist:
        raise PermissionError(f"Tenant {tenant_id} not found or inactive")

    if not TenantMembership.objects.filter(user_id=user_id, tenant=tenant, is_active=True).exists():
        raise PermissionError("You are not an active member of this tenant")

    roles = list(
        TenantUserRole.objects.filter(tenant=tenant, user_id=user_id)
        .values_list("role", flat=True)
        .order_by("role")
    )

    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "roles": roles,
    }


def list_my_modules(tenant_id: int) -> list[dict[str, Any]]:
    """Return modules that are enabled AND accessible to the current user in a tenant.

    Use this before calling finance/directory tools to know what's available.
    Any active tenant member can call this.
    """
    token = _get_token()
    user_id = _decode_token(token)

    from apps.accounts.models import User
    from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig
    from apps.tenants.permissions import has_effective_module_access

    try:
        user = User.objects.get(id=user_id)
        tenant = Tenant.objects.get(id=tenant_id, is_active=True)
    except (User.DoesNotExist, Tenant.DoesNotExist):
        raise PermissionError(f"Tenant {tenant_id} not found or user invalid")

    if not TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
        raise PermissionError("You are not an active member of this tenant")

    enabled_modules = (
        TenantModuleConfig.objects.filter(tenant=tenant, is_enabled=True)
        .values_list("module_key", flat=True)
    )

    return [
        {"module_key": key}
        for key in sorted(enabled_modules)
        if has_effective_module_access(user=user, tenant=tenant, module_key=key)
    ]


def get_tenant_info(tenant_id: int) -> dict[str, Any]:
    """Return public metadata for a tenant (admin or director only)."""
    _, tenant = require_admin_or_director(tenant_id)

    return {
        "id": tenant.id,
        "name": tenant.name,
        "subdomain": tenant.subdomain,
        "is_active": tenant.is_active,
        "telegram_otp_enabled": tenant.telegram_otp_enabled,
        "telegram_bot_username": tenant.telegram_bot_username,
    }


def list_module_configs(tenant_id: int) -> list[dict[str, Any]]:
    """Return all module enable/disable flags for a tenant (admin or director only)."""
    _, tenant = require_admin_or_director(tenant_id)

    from apps.tenants.models import TenantModuleConfig

    return json_safe(list(
        TenantModuleConfig.objects.filter(tenant=tenant)
        .order_by("module_key")
        .values("id", "module_key", "is_enabled")
    ))


def list_user_roles(tenant_id: int) -> list[dict[str, Any]]:
    """Return all user-role assignments for a tenant (admin only)."""
    _, tenant = require_admin_access(tenant_id)

    from apps.tenants.models import TenantUserRole

    return json_safe(list(
        TenantUserRole.objects.filter(tenant=tenant)
        .order_by("user_id", "role")
        .values("id", "user_id", "role")
    ))


def list_memberships(tenant_id: int) -> list[dict[str, Any]]:
    """Return all tenant memberships (admin only)."""
    _, tenant = require_admin_access(tenant_id)

    from apps.tenants.models import TenantMembership

    return json_safe(list(
        TenantMembership.objects.filter(tenant=tenant)
        .order_by("user_id")
        .values("id", "user_id", "is_active")
    ))
