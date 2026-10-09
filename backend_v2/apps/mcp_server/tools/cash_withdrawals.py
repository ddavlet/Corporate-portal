"""MCP tools for cash withdrawals (подтверждение получения снятых наличных)."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_admin_or_director
from apps.mcp_server.utils import json_safe

_MAX_LIMIT = 200


def _user_name(user) -> str | None:
    if user is None:
        return None
    return (user.full_name or "").strip() or user.username


def list_cash_withdrawal_receipts(
    tenant_id: int,
    status: str = "pending",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return PAYED withdrawal requests and whether the cash was confirmed as received.

    - status: pending (default) | confirmed | closed | all
    - limit: max records (default 50, max 200), oldest pending first

    Required roles: admin, director.
    """
    _, tenant = require_admin_or_director(tenant_id)

    from django.utils import timezone

    from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt

    allowed = {c for c, _ in CashWithdrawalReceipt.Status.choices}
    if status != "all" and status not in allowed:
        raise ValueError(f"Invalid status {status!r}; allowed: {', '.join(sorted(allowed))}, all")

    qs = CashWithdrawalReceipt.objects.filter(tenant=tenant).select_related(
        "request", "wallet__cash_register", "confirmed_by", "closed_by"
    )
    if status != "all":
        qs = qs.filter(status=status)

    now = timezone.now()
    limit = min(max(1, int(limit)), _MAX_LIMIT)
    out = []
    for r in qs.order_by("created_at", "id")[:limit]:
        register = r.wallet.cash_register if r.wallet.cash_register_id else None
        out.append({
            "id": r.id,
            "request_id": r.request_id,
            "request_title": r.request.title,
            "amount": r.amount,
            "currency": r.currency,
            "cash_register": ((register.name or "").strip() or register.currency) if register else None,
            "status": r.status,
            "created_at": r.created_at,
            "days_waiting": (now - r.created_at).days if r.status == CashWithdrawalReceipt.Status.PENDING else None,
            "alert_count": r.alert_count,
            "confirmed_by": _user_name(r.confirmed_by),
            "confirmed_at": r.confirmed_at,
            "closed_by": _user_name(r.closed_by),
            "closed_at": r.closed_at,
            "closed_comment": r.closed_comment,
        })
    return json_safe(out)
