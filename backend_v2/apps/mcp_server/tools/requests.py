"""MCP tools for the Requests (заявки) module."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe, validate_date

MODULE = "requests"
_MAX_LIMIT = 200


def _request_to_dict(r) -> dict[str, Any]:
    return {
        "id": r.id,
        "title": r.title,
        "status": r.status,
        "amount": str(r.amount),
        "currency": r.currency,
        "payment_type": r.payment_type,
        "urgency": r.urgency,
        "category": r.category,
        "vendor": r.vendor,
        "vendor_ref_id": r.vendor_ref_id,
        "contract_ref_id": r.contract_ref_id,
        "company_payer": r.company_payer,
        "payment_purpose": r.payment_purpose,
        "description": r.description,
        "billing_date": r.billing_date.isoformat() if r.billing_date else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "payed_at": r.payed_at,
        "created_by_id": r.created_by_id,
        "requester_id": r.requester_id,
        "expense_id": r.expense_id,
        "expense_ref_id": r.expense_ref_id,
        "expense_ref_target": r.expense_ref_target,
        "expense_year": r.expense_year,
        "expense_month": r.expense_month,
        "expense_day": r.expense_day,
        "file_link": r.file_link,
        "amortization_months": r.amortization_months,
        "amortization_start_date": (
            r.amortization_start_date.isoformat() if r.amortization_start_date else None
        ),
    }


_GROUP_BY = ("category", "vendor", "month", "status", "payment_type", "currency")


def _filtered_requests(
    tenant,
    *,
    status: str = "",
    currency: str = "",
    payment_type: str = "",
    urgency: str = "",
    category: str = "",
    vendor: str = "",
    contract_id: int = 0,
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    billing_date_from: str = "",
    billing_date_to: str = "",
):
    """Requests of `tenant` narrowed by the shared MCP filters (deleted ones are never included)."""
    from django.db.models import Q

    from apps.modules.requests.models import Request

    for value, name in (
        (date_from, "date_from"), (date_to, "date_to"),
        (billing_date_from, "billing_date_from"), (billing_date_to, "billing_date_to"),
    ):
        validate_date(value, name)

    qs = Request.objects.filter(tenant=tenant)

    statuses = [s.strip() for s in (status or "").split(",") if s.strip()]
    if statuses:
        qs = qs.filter(status__in=statuses)
    if currency:
        qs = qs.filter(currency=currency)
    if payment_type:
        qs = qs.filter(payment_type=payment_type)
    if urgency:
        qs = qs.filter(urgency=urgency)
    if category:
        qs = qs.filter(category__iexact=category.strip())
    if vendor:
        v = vendor.strip()
        qs = qs.filter(Q(vendor__icontains=v) | Q(vendor_ref__name__icontains=v))
    if contract_id:
        qs = qs.filter(contract_ref_id=int(contract_id))
    if search:
        t = search.strip()
        qs = qs.filter(
            Q(title__icontains=t) | Q(description__icontains=t) | Q(payment_purpose__icontains=t)
        )
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if billing_date_from:
        qs = qs.filter(billing_date__gte=billing_date_from)
    if billing_date_to:
        qs = qs.filter(billing_date__lte=billing_date_to)
    return qs


def list_requests(
    tenant_id: int,
    status: str = "",
    currency: str = "",
    payment_type: str = "",
    urgency: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
    category: str = "",
    vendor: str = "",
    contract_id: int = 0,
    search: str = "",
    billing_date_from: str = "",
    billing_date_to: str = "",
) -> list[dict[str, Any]]:
    """Return requests for a tenant with optional filtering.

    Filters (all optional):
    - status: DRAFT | 1 | 2 | 3 | 4 | 5 | APPROVED | PAYED | REJECTED, or several comma-separated
    - currency: UZS | USD | EUR | RUB
    - payment_type: Наличные | Перечисление | Пополнение | Платежная карта | Начисление ЗП
    - urgency: Низко | Обычно | Срочно
    - category: exact category name (case-insensitive)
    - vendor: substring of the vendor name
    - contract_id: requests linked to this contract
    - search: substring of title / description / payment purpose
    - date_from / date_to: ISO date strings (YYYY-MM-DD), filter on created_at
    - billing_date_from / billing_date_to: ISO date strings, filter on billing_date
    - limit: max records to return (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    qs = _filtered_requests(
        tenant, status=status, currency=currency, payment_type=payment_type, urgency=urgency,
        category=category, vendor=vendor, contract_id=contract_id, search=search,
        date_from=date_from, date_to=date_to,
        billing_date_from=billing_date_from, billing_date_to=billing_date_to,
    )

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return [_request_to_dict(r) for r in qs.order_by("-created_at")[:limit]]


def summarize_requests(
    tenant_id: int,
    group_by: str = "category",
    status: str = "",
    currency: str = "",
    payment_type: str = "",
    urgency: str = "",
    category: str = "",
    vendor: str = "",
    contract_id: int = 0,
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    billing_date_from: str = "",
    billing_date_to: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Count and sum requests per group (and per currency — amounts are never mixed across currencies).

    group_by: category | vendor | month (of billing_date) | status | payment_type | currency.
    Accepts the same filters as list_requests. Groups are sorted by total, largest first.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    if group_by not in _GROUP_BY:
        raise ValueError(f"Invalid group_by {group_by!r}; allowed: {', '.join(_GROUP_BY)}")

    from django.db.models import Count, F, Sum, Value
    from django.db.models.functions import Coalesce, NullIf, TruncMonth

    qs = _filtered_requests(
        tenant, status=status, currency=currency, payment_type=payment_type, urgency=urgency,
        category=category, vendor=vendor, contract_id=contract_id, search=search,
        date_from=date_from, date_to=date_to,
        billing_date_from=billing_date_from, billing_date_to=billing_date_to,
    )

    if group_by == "month":
        key_expr = TruncMonth("billing_date")
    elif group_by == "vendor":
        key_expr = Coalesce(NullIf(F("vendor_ref__name"), Value("")), F("vendor"))
    else:
        key_expr = F(group_by)

    rows = (
        qs.annotate(group_key=key_expr)
        .values("group_key", "currency")
        .annotate(count=Count("id"), total=Sum("amount"))
        .order_by("-total", "group_key")
    )
    limit = min(max(1, int(limit)), _MAX_LIMIT)
    all_rows = list(rows)
    totals = (
        qs.values("currency").annotate(count=Count("id"), total=Sum("amount")).order_by("currency")
    )
    return json_safe({
        "group_by": group_by,
        "groups": [
            {
                "key": (r["group_key"].strftime("%Y-%m") if group_by == "month" and r["group_key"] else r["group_key"]),
                "currency": r["currency"],
                "count": r["count"],
                "total": r["total"],
            }
            for r in all_rows[:limit]
        ],
        "groups_total": len(all_rows),
        "totals_by_currency": list(totals),
    })


def get_request(tenant_id: int, request_id: int) -> dict[str, Any]:
    """Return a single request by ID, including its approval steps."""
    _, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.requests.models import Request, Approval

    try:
        r = Request.objects.get(id=request_id, tenant=tenant)
    except Request.DoesNotExist:
        raise ValueError(f"Request {request_id} not found in this tenant")

    data = _request_to_dict(r)
    data["approvals"] = json_safe(list(
        Approval.objects.filter(request=r)
        .order_by("step")
        .values("id", "step", "step_type", "decision", "approver_user_id", "comment", "decided_at")
    ))
    return data


def list_request_categories(tenant_id: int) -> list[dict[str, Any]]:
    """Return all active request categories for a tenant."""
    _, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.requests.models import RequestCategory

    return json_safe(list(
        RequestCategory.objects.filter(tenant=tenant, is_active=True)
        .order_by("name")
        .values("id", "name", "is_active", "created_at")
    ))
