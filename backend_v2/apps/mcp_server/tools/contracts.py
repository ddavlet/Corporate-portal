"""MCP tools for the Contracts (договоры) module."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe, validate_date

MODULE = "contracts"
_MAX_LIMIT = 200
_STATUSES = ("accepted", "refused", "expired")


def _paid_totals(contract_ids: list[int]) -> dict[int, Decimal]:
    """PAYED requests per contract, counted only in the contract's own currency."""
    from django.db.models import F, Sum

    from apps.modules.requests.models import Request

    rows = (
        Request.objects.filter(
            contract_ref_id__in=contract_ids,
            status=Request.STATUS_PAYED,
            currency=F("contract_ref__currency"),
        )
        .values("contract_ref_id")
        .annotate(total=Sum("amount"))
    )
    return {r["contract_ref_id"]: r["total"] or Decimal("0") for r in rows}


def _contract_to_dict(c, paid: Decimal) -> dict[str, Any]:
    from apps.modules.contracts.services import effective_contract_display

    status, _ = effective_contract_display(c)
    remaining = c.contract_amount - paid if c.contract_amount is not None else None
    return {
        "id": c.id,
        "contract_number": c.contract_number,
        "vendor_id": c.vendor_id,
        "vendor": c.vendor.name,
        "status": status,
        "date_from": c.date_from,
        "date_to": c.date_to,
        "contract_amount": c.contract_amount,
        "currency": c.currency,
        "paid_total": paid,
        "remaining": remaining,
        "acc_number": c.acc_number,
        "has_file": bool(c.contract_file),
    }


def list_contracts(
    tenant_id: int,
    status: str = "",
    vendor_id: int = 0,
    search: str = "",
    active_on: str = "",
    expires_from: str = "",
    expires_to: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return contracts with the amount already paid on them.

    Filters (all optional):
    - status: accepted | refused | expired (expired = accepted with date_to in the past)
    - vendor_id: contracts with this vendor
    - search: substring of contract number or vendor name
    - active_on: contracts valid on this date (YYYY-MM-DD)
    - expires_from / expires_to: date_to within this range (YYYY-MM-DD)
    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    for value, name in ((active_on, "active_on"), (expires_from, "expires_from"), (expires_to, "expires_to")):
        validate_date(value, name)
    if status and status not in _STATUSES:
        raise ValueError(f"Invalid status {status!r}; allowed: {', '.join(_STATUSES)}")

    from django.db.models import Q
    from django.utils import timezone

    from apps.modules.contracts.models import Contract

    qs = Contract.objects.filter(tenant=tenant).select_related("vendor")
    today = timezone.localdate()
    if status == "refused":
        qs = qs.filter(contract_status=Contract.STATUS_REFUSED)
    elif status == "expired":
        qs = qs.filter(contract_status=Contract.STATUS_ACCEPTED, date_to__lt=today)
    elif status == "accepted":
        qs = qs.filter(contract_status=Contract.STATUS_ACCEPTED).filter(
            Q(date_to__isnull=True) | Q(date_to__gte=today)
        )
    if vendor_id:
        qs = qs.filter(vendor_id=int(vendor_id))
    if search:
        t = search.strip()
        qs = qs.filter(Q(contract_number__icontains=t) | Q(vendor__name__icontains=t))
    if active_on:
        qs = qs.filter(date_from__lte=active_on).filter(Q(date_to__isnull=True) | Q(date_to__gte=active_on))
    if expires_from:
        qs = qs.filter(date_to__gte=expires_from)
    if expires_to:
        qs = qs.filter(date_to__lte=expires_to)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    contracts = list(qs.order_by("-date_from", "-id")[:limit])
    paid = _paid_totals([c.id for c in contracts])
    return json_safe([_contract_to_dict(c, paid.get(c.id, Decimal("0"))) for c in contracts])


def get_contract(tenant_id: int, contract_id: int) -> dict[str, Any]:
    """Return one contract with its terms and all requests linked to it."""
    _, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.contracts.models import Contract
    from apps.modules.requests.models import Request

    try:
        c = Contract.objects.select_related("vendor").get(id=contract_id, tenant=tenant)
    except Contract.DoesNotExist:
        raise ValueError(f"Contract {contract_id} not found in this tenant")

    data = _contract_to_dict(c, _paid_totals([c.id]).get(c.id, Decimal("0")))
    data["contract_terms"] = c.contract_terms
    data["requests"] = list(
        Request.objects.filter(tenant=tenant, contract_ref=c)
        .order_by("-billing_date", "-id")
        .values("id", "title", "status", "amount", "currency", "billing_date", "created_at")
    )
    return json_safe(data)
