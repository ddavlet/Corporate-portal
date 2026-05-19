"""MCP tools for reference directories (справочники): vendors and wallets."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access
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
