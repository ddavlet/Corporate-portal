"""MCP tools for financial operations: cash, bank, corporate card, payroll."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe, validate_date

_MAX_LIMIT = 200

_PNL_REPORT_BUCKETS = ("revenue", "operational_expenses", "other_expenses", "invest_returns")


# ---------------------------------------------------------------------------
# Cash
# ---------------------------------------------------------------------------

def list_cash_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    currency: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return cash expenses for a tenant.

    Filters (all optional):
    - date_from / date_to: ISO date strings (YYYY-MM-DD), filter on expense_at
    - currency: UZS | USD | EUR | RUB
    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, "cash")

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.cashier.models import CashExpense

    qs = CashExpense.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(expense_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_at__date__lte=date_to)
    if currency:
        qs = qs.filter(currency=currency)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        qs.order_by("-expense_at")[:limit].values(
            "id", "external_id", "title", "amount", "currency",
            "expense_at", "expense_year", "expense_month", "expense_day",
            "note", "confirmed", "vendor_id", "wallet_id", "created_at",
        )
    ))


def list_cash_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return cash revenues for a tenant.

    Filters (all optional):
    - date_from / date_to: ISO date strings (YYYY-MM-DD)
    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, "cash")

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.cashier.models import CashRevenue

    qs = CashRevenue.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(revenue_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(revenue_at__date__lte=date_to)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        qs.order_by("-revenue_at")[:limit].values(
            "id", "external_id", "total_sum", "currency", "revenue_at",
            "source_year", "confirmed", "created_at",
        )
    ))


# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------

def list_bank_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return bank expenses for a tenant.

    Filters (all optional):
    - date_from / date_to: ISO date strings (YYYY-MM-DD), filter on doc_date
    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, "bank")

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.bank_expenses.models import BankExpense

    qs = BankExpense.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(doc_date__gte=date_from)
    if date_to:
        qs = qs.filter(doc_date__lte=date_to)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        qs.order_by("-doc_date")[:limit].values(
            "id", "doc_no", "doc_date", "process_date",
            "debit_turnover", "payment_purpose",
            "expense_year", "expense_month", "expense_day",
            "vendor_id", "wallet_id", "created_at",
        )
    ))


def list_bank_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return bank revenues for a tenant.

    Filters (all optional):
    - date_from / date_to: ISO date strings (YYYY-MM-DD), filter on doc_date
    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, "bank")

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.bank_expenses.models import BankRevenue

    qs = BankRevenue.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(doc_date__gte=date_from)
    if date_to:
        qs = qs.filter(doc_date__lte=date_to)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        qs.order_by("-doc_date")[:limit].values(
            "id", "doc_no", "doc_date", "process_date",
            "kredit_turnover", "payment_purpose",
            "account_name", "inn", "account_no", "mfo",
            "wallet_id", "created_at",
        )
    ))


# ---------------------------------------------------------------------------
# Corporate card
# ---------------------------------------------------------------------------

def list_card_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return corporate card expenses for a tenant.

    Filters (all optional):
    - date_from / date_to: ISO date strings (YYYY-MM-DD)
    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, "corporate_card")

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.corporate_card.models import CardExpense

    qs = CardExpense.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(expense_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_at__date__lte=date_to)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        qs.order_by("-expense_at")[:limit].values(
            "id", "title", "amount", "currency", "expense_at",
            "note", "wallet_id", "created_at",
        )
    ))


def list_card_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return corporate card revenues for a tenant.

    Filters (all optional):
    - date_from / date_to: ISO date strings (YYYY-MM-DD)
    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, "corporate_card")

    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.corporate_card.models import CardRevenue

    qs = CardRevenue.objects.filter(tenant=tenant)
    if date_from:
        qs = qs.filter(revenue_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(revenue_at__date__lte=date_to)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        qs.order_by("-revenue_at")[:limit].values(
            "id",
            "external_id",
            "total_sum",
            "currency",
            "revenue_at",
            "operation",
            "counterparty",
            "comment",
            "confirmed",
            "payload",
            "wallet_id",
            "created_at",
        )
    ))


# ---------------------------------------------------------------------------
# Reports — PnL and Cashflow
# ---------------------------------------------------------------------------
#
# build_pnl_payload_from_db / build_cashflow_payload_from_db always return
# every line since pnl_config.start_month, unbounded — for a tenant with a
# year+ of history that is thousands of rows and can blow up a caller's
# token budget. The MCP tools narrow that down after the fact (date_from /
# date_to filter, optional aggregate mode) without touching the builders
# themselves, since those are shared with the reports REST API.

def _row_date(row: dict[str, Any]) -> date:
    """Extract the calendar date a report line belongs to.

    Report rows use either a full ISO date/datetime string or, for amortized
    schedule rows, a bare "YYYY-MM" period.
    """
    raw = str(row.get("date") or "")
    if len(raw) >= 10:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    if len(raw) == 7:
        return datetime.strptime(raw, "%Y-%m").date()
    raise ValueError(f"Unrecognized report row date: {raw!r}")


def _filter_bucket_by_date(rows: list[dict[str, Any]], date_from: str, date_to: str) -> list[dict[str, Any]]:
    if not date_from and not date_to:
        return rows
    lo = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    hi = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None
    out = []
    for row in rows:
        d = _row_date(row)
        if lo and d < lo:
            continue
        if hi and d > hi:
            continue
        out.append(row)
    return out


def _aggregate_bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = Decimal("0")
    by_month: dict[str, Decimal] = {}
    by_category: dict[str, Decimal] = {}
    for row in rows:
        amount = Decimal(str(row["amount"]))
        total += amount
        month_key = _row_date(row).strftime("%Y-%m")
        by_month[month_key] = by_month.get(month_key, Decimal("0")) + amount
        cat = str(row.get("category") or "")
        by_category[cat] = by_category.get(cat, Decimal("0")) + amount
    return {
        "total": str(total),
        "count": len(rows),
        "by_month": {k: str(v) for k, v in sorted(by_month.items())},
        "by_category": {k: str(v) for k, v in sorted(by_category.items())},
    }


def _shrink_pnl_payload(payload: dict[str, Any], *, date_from: str, date_to: str, aggregate: bool) -> dict[str, Any]:
    for key in _PNL_REPORT_BUCKETS:
        payload[key] = _filter_bucket_by_date(payload[key], date_from, date_to)
    if aggregate:
        for key in _PNL_REPORT_BUCKETS:
            payload[key] = _aggregate_bucket(payload[key])
        payload["aggregated"] = True
    return payload


def get_pnl_report(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    aggregate: bool = False,
) -> dict:
    """Build and return the PnL report from the database.

    Uses the same pnl_config as the tenant's backend PnL settings.
    Raises ValueError if report settings are not configured or a date filter
    is malformed.

    - date_from / date_to: ISO date strings (YYYY-MM-DD); narrow the report
      window on top of pnl_config.start_month (all optional).
    - aggregate: when True, each bucket collapses to totals (by_month,
      by_category, count) instead of individual line items.
    """
    _, tenant = require_module_access(tenant_id, "reports")
    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.reports.pnl_builder import (
        build_pnl_payload_from_db,
        ReportSettingsMissing,
        ReportSettingsInvalid,
    )

    try:
        payload = build_pnl_payload_from_db(tenant=tenant, query_params={})
    except ReportSettingsMissing as e:
        raise ValueError(str(e))
    except ReportSettingsInvalid as e:
        raise ValueError(str(e))

    return _shrink_pnl_payload(payload, date_from=date_from, date_to=date_to, aggregate=aggregate)


def get_cashflow_report(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    aggregate: bool = False,
) -> dict:
    """Build and return the Cashflow report from the database.

    Uses the same pnl_config as PnL (cashflow reuses the same filter config).
    Raises ValueError if report settings are not configured or a date filter
    is malformed.

    - date_from / date_to: ISO date strings (YYYY-MM-DD); narrow the report
      window on top of pnl_config.start_month (all optional).
    - aggregate: when True, each bucket collapses to totals (by_month,
      by_category, count) instead of individual line items.
    """
    _, tenant = require_module_access(tenant_id, "reports")
    validate_date(date_from, "date_from")
    validate_date(date_to, "date_to")

    from apps.modules.reports.cashflow_builder import (
        build_cashflow_payload_from_db,
        ReportSettingsInvalid,
    )
    from apps.modules.reports.pnl_builder import ReportSettingsMissing

    try:
        payload = build_cashflow_payload_from_db(tenant=tenant, query_params={})
    except ReportSettingsMissing as e:
        raise ValueError(str(e))
    except ReportSettingsInvalid as e:
        raise ValueError(str(e))

    return _shrink_pnl_payload(payload, date_from=date_from, date_to=date_to, aggregate=aggregate)


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------

def list_payroll_documents(
    tenant_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return payroll documents for a tenant.

    - limit: max records (default 50, max 200)
    """
    _, tenant = require_module_access(tenant_id, "payroll")

    from apps.modules.payroll.models import PayrollDocument

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe(list(
        PayrollDocument.objects.filter(tenant=tenant)
        .order_by("-created_at")[:limit]
        .values("id", "doc_id", "created_at")
    ))


def get_payroll_document(
    tenant_id: int,
    document_id: int,
) -> dict[str, Any]:
    """Return a payroll document and all its lines."""
    _, tenant = require_module_access(tenant_id, "payroll")

    from apps.modules.payroll.models import PayrollDocument

    try:
        doc = PayrollDocument.objects.get(id=document_id, tenant=tenant)
    except PayrollDocument.DoesNotExist:
        raise ValueError(f"PayrollDocument {document_id} not found in this tenant")

    lines = json_safe(list(
        doc.lines.order_by("line_no").values(
            "id", "line_no", "employee", "item", "description",
            "sum", "days_plan", "days_fact", "period_start", "period_end", "approval",
        )
    ))
    return {
        "id": doc.id,
        "doc_id": doc.doc_id,
        "created_at": doc.created_at.isoformat(),
        "lines": lines,
    }
