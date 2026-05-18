"""MCP tools for the Requests (заявки) module."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe

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
        "company_payer": r.company_payer,
        "payment_purpose": r.payment_purpose,
        "description": r.description,
        "billing_date": str(r.billing_date),
        "created_at": r.created_at.isoformat(),
        "submitted_at": r.submitted_at.isoformat(),
        "created_by_id": r.created_by_id,
        "requester_id": r.requester_id,
    }


def list_requests(
    token: str,
    tenant_id: int,
    status: str = "",
    currency: str = "",
    payment_type: str = "",
    urgency: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return requests for a tenant with optional filtering.

    Filters (all optional):
    - status: DRAFT | 1 | 2 | 3 | 4 | 5 | APPROVED | PAYED | REJECTED
    - currency: UZS | USD | EUR | RUB
    - payment_type: Наличные | Перечисление | Пополнение | Платежная карта
    - urgency: Низко | Обычно | Срочно
    - date_from / date_to: ISO date strings (YYYY-MM-DD), filter on created_at
    - limit: max records to return (default 50, max 200)
    """
    _, tenant = require_module_access(token, tenant_id, MODULE)

    from apps.modules.requests.models import Request

    qs = Request.objects.filter(tenant=tenant)

    if status:
        qs = qs.filter(status=status)
    if currency:
        qs = qs.filter(currency=currency)
    if payment_type:
        qs = qs.filter(payment_type=payment_type)
    if urgency:
        qs = qs.filter(urgency=urgency)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return [_request_to_dict(r) for r in qs.order_by("-created_at")[:limit]]


def get_request(token: str, tenant_id: int, request_id: int) -> dict[str, Any]:
    """Return a single request by ID, including its approval steps."""
    _, tenant = require_module_access(token, tenant_id, MODULE)

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


def list_request_categories(token: str, tenant_id: int) -> list[dict[str, Any]]:
    """Return all active request categories for a tenant."""
    _, tenant = require_module_access(token, tenant_id, MODULE)

    from apps.modules.requests.models import RequestCategory

    return json_safe(list(
        RequestCategory.objects.filter(tenant=tenant, is_active=True)
        .order_by("name")
        .values("id", "name", "is_active", "created_at")
    ))
