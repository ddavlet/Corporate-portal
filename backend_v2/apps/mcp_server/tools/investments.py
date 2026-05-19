"""MCP tools for the Investments module (капитал, выплаты инвесторам, график)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe, validate_date

MODULE = "investments"
_MAX_LIMIT = 200


def list_invest_companies(
    tenant_id: int,
    *,
    is_active: bool | None = None,
    name_search: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List investment companies (юрлица / проекты) for a tenant.

    Companies group returns, project investments, and payout schedules.
    Only meaningful when the tenant uses companies in investment settings
    (see get_investment_form_config). Filter by name to resolve company_id
    for other investment tools.

    Required roles: admin, director, investor (module: investments).
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.investments.models import InvestCompany

    qs = InvestCompany.objects.filter(tenant=tenant)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if name_search:
        qs = qs.filter(name__icontains=name_search.strip())

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(
        list(
            qs.order_by("name", "id")[:limit].values(
                "id", "name", "comment", "is_active", "created_at", "last_edit_at"
            )
        )
    )


def list_invest_returns(
    tenant_id: int,
    *,
    date_from: str = "",
    date_to: str = "",
    return_type: str = "",
    recipient: str = "",
    company_id: int = 0,
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
    company_id (0 = all), confirmed (true/false), limit (max 200).

    Roles: admin, director, investor.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.investments.models import InvestReturn

    qs = InvestReturn.objects.filter(tenant=tenant).select_related("company")
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if return_type:
        qs = qs.filter(type=return_type.strip())
    if recipient:
        qs = qs.filter(recipient=recipient.strip())
    if company_id:
        qs = qs.filter(company_id=company_id)
    if confirmed is not None:
        qs = qs.filter(confirmed=confirmed)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    rows = []
    for r in qs.order_by("-date", "-id")[:limit]:
        rows.append(
            {
                "id": r.id,
                "company_id": r.company_id,
                "company_name": r.company.name if r.company else None,
                "date": r.date.isoformat(),
                "billing_date": r.billing_date.isoformat(),
                "sum": str(r.sum),
                "currency": r.currency,
                "sum_uzs": str(r.sum_uzs) if r.sum_uzs is not None else None,
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
    company_id: int = 0,
    confirmed: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List capital investments into projects (вложения в проекты).

  Unlike invest_returns (money out to investors), these are inbound /
  registered capital amounts tied to a company/project dimension.

  Filters: date_from, date_to (YYYY-MM-DD), company_id, confirmed.
  Required roles: admin, director, investor.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.investments.models import ProjectInvestment

    qs = ProjectInvestment.objects.filter(tenant=tenant).select_related("company")
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if company_id:
        qs = qs.filter(company_id=company_id)
    if confirmed is not None:
        qs = qs.filter(confirmed=confirmed)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    rows = []
    for r in qs.order_by("-date", "-id")[:limit]:
        rows.append(
            {
                "id": r.id,
                "company_id": r.company_id,
                "company_name": r.company.name if r.company else None,
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
    company_id: int = 0,
    is_paid: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List planned investment payout schedule rows (график выплат).

  Each row is a future or past scheduled payout: due date, planned amount,
  whether it was paid, and how much was actually paid (payment_amount).
  Use with list_invest_returns to compare plan vs fact.

  Filters: date_from / date_to on payout_date, company_id, is_paid.
  Required roles: admin, director, investor.
    """
    _, tenant = require_module_access(tenant_id, MODULE)

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.investments.models import InvestPayoutSchedule

    qs = InvestPayoutSchedule.objects.filter(tenant=tenant).select_related("company")
    if date_from:
        qs = qs.filter(payout_date__gte=date_from)
    if date_to:
        qs = qs.filter(payout_date__lte=date_to)
    if company_id:
        qs = qs.filter(company_id=company_id)
    if is_paid is not None:
        qs = qs.filter(is_paid=is_paid)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    rows = []
    for r in qs.order_by("-payout_date", "-id")[:limit]:
        rows.append(
            {
                "id": r.id,
                "company_id": r.company_id,
                "company_name": r.company.name if r.company else None,
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
    """Return per-tenant investment UI rules (companies on/off, allowed return types).

  Call before other investment tools to see whether company_id filters apply
  and which return_type strings are valid for this tenant.

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
                "uses_companies": True,
                "allowed_return_types": [],
            }
        )

    return json_safe(
        {
            "tenant_id": tenant.id,
            "configured": True,
            "uses_companies": cfg.uses_companies,
            "allowed_return_types": list(cfg.allowed_return_types or []),
        }
    )
