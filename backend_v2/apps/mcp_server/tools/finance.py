"""MCP tools for financial operations: cash, bank, corporate card, payroll."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe, validate_date

_MAX_LIMIT = 200


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
            "title",
            "amount",
            "currency",
            "revenue_at",
            "note",
            "confirmed",
            "wallet_id",
            "created_at",
        )
    ))


# ---------------------------------------------------------------------------
# Reports — PnL and Cashflow
# ---------------------------------------------------------------------------

def get_pnl_report(tenant_id: int) -> dict:
    """Build and return the full PnL report from the database.

    Uses the same pnl_config as the tenant's backend PnL settings.
    Raises ValueError if report settings are not configured.
    """
    _, tenant = require_module_access(tenant_id, "reports")

    from apps.modules.reports.pnl_builder import (
        build_pnl_payload_from_db,
        ReportSettingsMissing,
        ReportSettingsInvalid,
    )

    try:
        return build_pnl_payload_from_db(tenant=tenant, query_params={})
    except ReportSettingsMissing as e:
        raise ValueError(str(e))
    except ReportSettingsInvalid as e:
        raise ValueError(str(e))


def get_cashflow_report(tenant_id: int) -> dict:
    """Build and return the full Cashflow report from the database.

    Uses the same pnl_config as PnL (cashflow reuses the same filter config).
    Raises ValueError if report settings are not configured.
    """
    _, tenant = require_module_access(tenant_id, "reports")

    from apps.modules.reports.cashflow_builder import (
        build_cashflow_payload_from_db,
        ReportSettingsInvalid,
    )
    from apps.modules.reports.pnl_builder import ReportSettingsMissing

    try:
        return build_cashflow_payload_from_db(tenant=tenant, query_params={})
    except ReportSettingsMissing as e:
        raise ValueError(str(e))
    except ReportSettingsInvalid as e:
        raise ValueError(str(e))


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
