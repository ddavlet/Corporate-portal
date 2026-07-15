"""MCP tools for the Budgets module (лимиты по категориям заявок)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe
from apps.modules.budgets.serializers import _period_date_range

MODULE = "budgets"
_MAX_LIMIT = 200


def _parse_year_period(*, year: int | None, period: int | None) -> tuple[int, int]:
    today = timezone.localdate()
    y = int(year) if year is not None else today.year
    p = int(period) if period is not None else today.month
    return y, max(1, min(12, p))


def _compute_budget_spent(budget, *, year: int, period_index: int) -> Decimal:
    from apps.modules.requests.models import Request

    start, end = _period_date_range(budget.period_type, year, period_index)
    total = (
        Request.objects.filter(
            tenant=budget.tenant,
            category=budget.category.name,
            currency=budget.currency,
            status__in=[Request.STATUS_APPROVED, Request.STATUS_PAYED],
            billing_date__gte=start,
            billing_date__lt=end,
            source_tenant__isnull=True,
        ).aggregate(total=Sum("amount"))["total"]
    )
    return total or Decimal("0")


def _budget_row(budget, *, year: int, period_index: int) -> dict[str, Any]:
    spent = _compute_budget_spent(budget, year=year, period_index=period_index)
    limit = budget.limit_amount
    remaining = limit - spent
    utilization = round(float(spent / limit * 100), 1) if limit else 0.0
    start, end = _period_date_range(budget.period_type, year, period_index)
    return {
        "id": budget.id,
        "name": budget.name,
        "category_id": budget.category_id,
        "category_name": budget.category.name,
        "period_type": budget.period_type,
        "limit_amount": str(limit),
        "currency": budget.currency,
        "is_active": budget.is_active,
        "period_year": year,
        "period_index": period_index,
        "period_start": start.isoformat(),
        "period_end_exclusive": end.isoformat(),
        "spent_amount": str(spent),
        "remaining_amount": str(remaining),
        "utilization_pct": utilization,
        "created_at": budget.created_at.isoformat() if budget.created_at else None,
    }


def list_budgets(
    tenant_id: int,
    *,
    year: int | None = None,
    period: int | None = None,
    category_name: str = "",
    is_active: bool | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List budgets (бюджеты) with spend vs limit for a calendar period.

  A budget caps spending on payment requests in one RequestCategory for a
  period (monthly, quarterly, or yearly). Spend is computed from APPROVED and
  PAYED requests matched by category name, currency, and billing_date —
  the same rules as the Kolberg UI.

  period_type on each row: monthly | quarterly | yearly.
  period_index is always a month number 1–12 (for quarterly budgets the month
  maps to its quarter, same as the web app).

  Pass year + period to evaluate utilization (defaults: current year/month).
  Example: year=2026, period=3 → March 2026 for monthly budgets.

  Filters: category_name (exact category label), is_active.
  Required roles: admin, director, accountant, approver (module: budgets).
    """
    _, tenant = require_module_access(tenant_id, MODULE)
    year_val, period_index = _parse_year_period(year=year, period=period)

    from apps.modules.budgets.models import Budget

    qs = Budget.objects.filter(tenant=tenant).select_related("category")
    if category_name:
        qs = qs.filter(category__name=category_name.strip())
    if is_active is not None:
        qs = qs.filter(is_active=is_active)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(
        [
            _budget_row(b, year=year_val, period_index=period_index)
            for b in qs.order_by("name", "id")[:limit]
        ]
    )


def get_budget(
    tenant_id: int,
    budget_id: int,
    *,
    year: int | None = None,
    period: int | None = None,
) -> dict[str, Any]:
    """Get one budget with spend, remaining, and utilization for a period.

  Use list_budgets first to find budget_id. Same spend rules as list_budgets.
  Required roles: admin, director, accountant, approver.
    """
    _, tenant = require_module_access(tenant_id, MODULE)
    year_val, period_index = _parse_year_period(year=year, period=period)

    from apps.modules.budgets.models import Budget

    try:
        budget = Budget.objects.select_related("category").get(id=budget_id, tenant=tenant)
    except Budget.DoesNotExist:
        raise ValueError(f"Budget {budget_id} not found in this tenant")

    return json_safe(_budget_row(budget, year=year_val, period_index=period_index))


def list_budget_spend_requests(
    tenant_id: int,
    budget_id: int,
    *,
    year: int | None = None,
    period: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List payment requests that count toward a budget's spend in a period.

  Only APPROVED and PAYED requests with matching category, currency, and
  billing_date inside the budget period are included — mirrors the UI
  spend-detail drill-down.

  Required roles: admin, director, accountant, approver.
    """
    _, tenant = require_module_access(tenant_id, MODULE)
    year_val, period_index = _parse_year_period(year=year, period=period)

    from apps.modules.budgets.models import Budget
    from apps.modules.requests.models import Request

    try:
        budget = Budget.objects.select_related("category").get(id=budget_id, tenant=tenant)
    except Budget.DoesNotExist:
        raise ValueError(f"Budget {budget_id} not found in this tenant")

    start, end = _period_date_range(budget.period_type, year_val, period_index)
    qs = Request.objects.filter(
        tenant=tenant,
        category=budget.category.name,
        currency=budget.currency,
        status__in=[Request.STATUS_APPROVED, Request.STATUS_PAYED],
        billing_date__gte=start,
        billing_date__lt=end,
        source_tenant__isnull=True,
    ).order_by("-billing_date")

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(
        list(
            qs[:limit].values(
                "id",
                "title",
                "amount",
                "currency",
                "category",
                "status",
                "billing_date",
                "payment_type",
            )
        )
    )
