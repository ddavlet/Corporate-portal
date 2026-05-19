"""MCP tools for reference directories (справочники): vendors, wallets, users."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access, require_admin_or_director
from apps.mcp_server.utils import json_safe

_MAX_LIMIT = 500


def list_vendors(
    tenant_id: int,
    kind: str = "",
    name_search: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return vendors from the tenant directory.

    Filters (all optional):
    - kind: cash | transfer
    - name_search: case-insensitive substring match on vendor name
    - limit: max records (default 100, max 500)
    """
    _, tenant = require_module_access(tenant_id, "vendors")

    from apps.modules.vendors.models import Vendor

    qs = Vendor.objects.filter(tenant=tenant)
    if kind:
        qs = qs.filter(kind=kind)
    if name_search:
        qs = qs.filter(name__icontains=name_search)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        qs.order_by("name")[:limit].values(
            "id", "kind", "name", "inn", "account_number", "created_at", "created_by_id"
        )
    ))


def list_active_users(tenant_id: int) -> list[dict[str, Any]]:
    """Return active members of a tenant with their roles.

    Only non-sensitive fields: id, full_name, username, roles.
    No passwords, emails, telegram IDs or other PII.

    Required roles: admin, director.
    """
    _, tenant = require_admin_or_director(tenant_id)

    from apps.tenants.models import TenantMembership, TenantUserRole

    memberships = (
        TenantMembership.objects
        .filter(tenant=tenant, is_active=True)
        .select_related("user")
        .order_by("user__full_name")
    )

    roles_qs = TenantUserRole.objects.filter(tenant=tenant).values("user_id", "role")
    roles_by_user: dict[int, list[str]] = {}
    for r in roles_qs:
        roles_by_user.setdefault(r["user_id"], []).append(r["role"])

    return [
        {
            "id": m.user_id,
            "full_name": m.user.full_name,
            "username": m.user.username,
            "roles": roles_by_user.get(m.user_id, []),
        }
        for m in memberships
    ]


def list_wallets(tenant_id: int) -> list[dict[str, Any]]:
    """Return all wallets (cash registers and bank/card accounts) for a tenant."""
    _, tenant = require_module_access(tenant_id, "wallets")

    from apps.modules.wallets.models import Wallet

    return json_safe(list(
        Wallet.objects.filter(tenant=tenant)
        .order_by("wallet_type", "id")
        .values(
            "id", "wallet_type", "currency",
            "opening_balance", "opening_balance_at",
            "is_visible_in_cash_section",
            "cash_register_id", "bank_account_id", "corporate_card_account_id",
        )
    ))
