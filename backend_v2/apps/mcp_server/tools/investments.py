"""MCP tools for the Investments module (капитал, выплаты инвесторам, график)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe, validate_date
from apps.modules.investments.services import clamp_rate_date_to_cbu_availability, usd_uzs_equivalents_for_read

MODULE = "investments"
_MAX_LIMIT = 200


def list_invest_returns(
    tenant_id: int,
    *,
    date_from: str = "",
    date_to: str = "",
    return_type: str = "",
    recipient: str = "",
    confirmed: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List investor payouts (выплаты / возвраты) in the Investments module.

    Each row is money paid out to an investor or partner: dividends, interest,
    profit share, or return of principal. Flows into PnL (invest_returns) by
    billing_date, like payment requests.

    return_type (DB values): дивиденды | проценты | доля_прибыли | тело_инвестиций
    recipient: инвестор | партнер

    Optional filters: date_from, date_to (YYYY-MM-DD), return_type, recipient,
    confirmed (true/false), limit (max 200).

    Roles: admin, director, investor.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.investments.models import InvestReturn

    qs = InvestReturn.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if return_type:
        qs = qs.filter(type=return_type.strip())
    if recipient:
        qs = qs.filter(recipient=recipient.strip())
    if confirmed is not None:
        qs = qs.filter(confirmed=confirmed)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    rows = []
    rate_memo: dict = {}
    for r in qs.order_by("-date", "-id")[:limit]:
        rate_date = clamp_rate_date_to_cbu_availability(requested=r.date)
        sum_usd, sum_uzs = usd_uzs_equivalents_for_read(
            sum_val=r.sum, currency=r.currency, rate_date=rate_date, memo=rate_memo
        )
        rows.append(
            {
                "id": r.id,
                "date": r.date.isoformat(),
                "billing_date": r.billing_date.isoformat(),
                "sum": str(r.sum),
                "currency": r.currency,
                "sum_usd": str(sum_usd) if sum_usd is not None else None,
                "sum_uzs": str(sum_uzs) if sum_uzs is not None else None,
                "type": r.type,
                "recipient": r.recipient,
                "confirmed": r.confirmed,
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return json_safe(rows)


def list_project_investments(
    tenant_id: int,
    *,
    date_from: str = "",
    date_to: str = "",
    confirmed: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List capital investments into projects (вложения в проекты).

  Unlike invest_returns (money out to investors), these are inbound /
  registered capital amounts of the tenant.

  Filters: date_from, date_to (YYYY-MM-DD), confirmed.
  Required roles: admin, director, investor.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.investments.models import ProjectInvestment

    qs = ProjectInvestment.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if confirmed is not None:
        qs = qs.filter(confirmed=confirmed)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    rows = []
    for r in qs.order_by("-date", "-id")[:limit]:
        rows.append(
            {
                "id": r.id,
                "date": r.date.isoformat(),
                "amount": str(r.amount),
                "currency": r.currency,
                "confirmed": r.confirmed,
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return json_safe(rows)


def list_invest_payout_schedule(
    tenant_id: int,
    *,
    date_from: str = "",
    date_to: str = "",
    is_paid: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List planned investment payout schedule rows (график выплат).

  Each row is a future or past scheduled payout: due date, planned amount,
  whether it was paid, and how much was actually paid (payment_amount).
  Use with list_invest_returns to compare plan vs fact.

  Filters: date_from / date_to on payout_date, is_paid.
  Required roles: admin, director, investor.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.investments.models import InvestPayoutSchedule

    qs = InvestPayoutSchedule.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(payout_date__gte=date_from)
    if date_to:
        qs = qs.filter(payout_date__lte=date_to)
    if is_paid is not None:
        qs = qs.filter(is_paid=is_paid)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    rows = []
    for r in qs.order_by("-payout_date", "-id")[:limit]:
        rows.append(
            {
                "id": r.id,
                "payout_date": r.payout_date.isoformat(),
                "amount": str(r.amount),
                "currency": r.currency,
                "is_paid": r.is_paid,
                "payment_amount": str(r.payment_amount),
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return json_safe(rows)


def get_investment_form_config(tenant_id: int) -> dict[str, Any]:
    """Return per-tenant investment UI rules (allowed return types).

  Call before other investment tools to see which return_type strings are
  valid for this tenant.

  Required roles: admin, director, investor.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.investments.models import InvestmentFormConfig

    try:
        cfg = InvestmentFormConfig.objects.get(tenant=tenant)
    except InvestmentFormConfig.DoesNotExist:
        return json_safe(
            {
                "tenant_id": tenant.id,
                "configured": False,
                "allowed_return_types": [],
            }
        )

    return json_safe(
        {
            "tenant_id": tenant.id,
            "configured": True,
            "allowed_return_types": list(cfg.allowed_return_types or []),
        }
    )
