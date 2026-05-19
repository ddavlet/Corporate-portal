"""MCP tools for tenant configuration: module flags, user roles, memberships."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_admin_access, require_admin_or_director
from apps.mcp_server.utils import json_safe


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
