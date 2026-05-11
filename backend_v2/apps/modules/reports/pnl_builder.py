from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.models import InvestReturn
from apps.modules.requests.models import Request
from apps.modules.reports.models import TenantReportSettings


class ReportSettingsMissing(Exception):
    """No TenantReportSettings row for tenant."""


class ReportSettingsInvalid(Exception):
    """pnl_config JSON is missing required keys or has invalid values."""


def _parse_start_month(value: str) -> date:
    text = (value or "").strip()
    try:
        y, m = text.split("-", 1)
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError) as exc:
        raise ReportSettingsInvalid(f"Invalid start_month {value!r}, expected YYYY-MM.") from exc


def _iso_local(dt: datetime | date | None) -> str:
    if dt is None:
        return ""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, datetime):
        if settings.USE_TZ and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        local = timezone.localtime(dt) if settings.USE_TZ else dt
        return local.isoformat()
    return ""


def _cash_operation_label(row: CashRevenue) -> str:
    payload = row.payload if isinstance(row.payload, dict) else {}
    op = payload.get("operation")
    if op is not None and str(op).strip():
        return str(op).strip()
    return str(row.operation or "").strip()


def validate_pnl_config_dict(cfg: dict[str, Any]) -> None:
    """Raise ReportSettingsInvalid if cfg cannot drive backend PnL."""
    required = (
        "start_month",
        "cash_exclude_operations",
        "request_exclude_categories",
        "income_tax_payment_purpose",
        "invest_return_exclude_types",
    )
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ReportSettingsInvalid(f"pnl_config missing keys: {missing}")

    _parse_start_month(str(cfg["start_month"]))

    if not isinstance(cfg["cash_exclude_operations"], list):
        raise ReportSettingsInvalid("cash_exclude_operations must be a list")
    if not isinstance(cfg["request_exclude_categories"], list):
        raise ReportSettingsInvalid("request_exclude_categories must be a list")
    if not isinstance(cfg["invest_return_exclude_types"], list):
        raise ReportSettingsInvalid("invest_return_exclude_types must be a list")


def get_pnl_config_or_raise(*, tenant) -> dict[str, Any]:
    try:
        row = TenantReportSettings.objects.get(tenant_id=tenant.id)
    except TenantReportSettings.DoesNotExist as exc:
        raise ReportSettingsMissing(f"No tenant_report_settings for tenant_id={tenant.id}") from exc

    cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
    validate_pnl_config_dict(cfg)

    return cfg


def build_pnl_payload_from_db(*, tenant, query_params: dict[str, Any]) -> dict[str, Any]:
    """
    Build raw PnL blocks from ORM (same logical shape as n8n webhook output before enrichment).

    Excludes manual investment-return calendar (Q1) and CORPORATE/amort view (Q6) per plan v1.
    """
    del query_params  # reserved; frontend currently sends no params

    cfg = get_pnl_config_or_raise(tenant=tenant)
    start = _parse_start_month(str(cfg["start_month"]))
    cash_exclude = {str(x).strip() for x in cfg["cash_exclude_operations"] if str(x).strip()}
    cat_exclude = {str(x).strip() for x in cfg["request_exclude_categories"] if str(x).strip()}
    income_tax_label = str(cfg["income_tax_payment_purpose"]).strip()
    invest_type_exclude = {str(x).strip() for x in cfg["invest_return_exclude_types"] if str(x).strip()}

    snapshot = {
        "start_month": str(cfg["start_month"]).strip(),
        "cash_exclude_operations": sorted(cash_exclude),
        "request_exclude_categories": sorted(cat_exclude),
        "income_tax_payment_purpose": income_tax_label,
        "invest_return_exclude_types": sorted(invest_type_exclude),
    }

    revenue: list[dict[str, Any]] = []

    for br in BankRevenue.objects.filter(tenant_id=tenant.id).order_by("doc_date", "id"):
        revenue.append(
            {
                "id": str(br.id),
                "date": br.doc_date.isoformat(),
                "amount": str(Decimal(br.kredit_turnover)),
                "category": "Поступление в банк",
                "purpose": "Поступление",
                "description": str(br.payment_purpose or ""),
            }
        )

    for cr in CashRevenue.objects.filter(tenant_id=tenant.id, confirmed=True).order_by("revenue_at", "id"):
        op_label = _cash_operation_label(cr)
        if op_label in cash_exclude:
            continue
        payload = cr.payload if isinstance(cr.payload, dict) else {}
        cat = str(payload.get("operation") or cr.operation or "").strip()
        revenue.append(
            {
                "id": str(cr.id),
                "date": _iso_local(cr.revenue_at) if cr.revenue_at else "",
                "amount": str(Decimal(cr.total_sum)),
                "purpose": str(cr.operation or ""),
                "description": str(cr.counterparty or ""),
                "category": cat or "Без категории",
            }
        )

    operational_expenses: list[dict[str, Any]] = []
    other_expenses: list[dict[str, Any]] = []

    qs = (
        Request.objects.filter(
            tenant_id=tenant.id,
            status=Request.STATUS_PAYED,
            billing_date__gte=start,
        )
        .exclude(payment_type=Request.PAYMENT_TYPE_CARD)
        .order_by("billing_date", "id")
    )

    for req in qs:
        cat = str(req.category or "").strip()
        if cat in cat_exclude:
            continue

        purpose = str(req.payment_purpose or "").strip()
        base_item = {
            "id": str(req.id),
            "amount": str(Decimal(req.amount)),
            "category": cat,
            "purpose": purpose,
            "description": str(req.description or ""),
        }

        if purpose == income_tax_label:
            base_item["date"] = req.billing_date.isoformat()
            other_expenses.append(base_item)
            continue

        months = int(req.amortization_months or 1)
        if months < 2:
            base_item["date"] = req.billing_date.isoformat()
            operational_expenses.append(base_item)
        else:
            amt = (Decimal(req.amount) / Decimal(months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            start_d = req.amortization_start_date or req.billing_date
            base_item["amount"] = str(amt)
            base_item["date"] = start_d.isoformat()
            operational_expenses.append(base_item)

    invest_returns: list[dict[str, Any]] = []
    for ir in (
        InvestReturn.objects.filter(tenant_id=tenant.id, confirmed=True)
        .exclude(sum_uzs__isnull=True)
        .order_by("date", "id")
    ):
        if str(ir.type or "").strip() in invest_type_exclude:
            continue
        invest_returns.append(
            {
                "id": str(ir.id),
                "date": ir.date.isoformat(),
                "amount": str(Decimal(ir.sum_uzs)),
                "category": "Дивиденды",
                "purpose": "Выплата доли",
                "description": f"Получатель: {ir.get_recipient_display()}",
            }
        )

    metadata = {
        "start_month": str(cfg["start_month"]).strip(),
    }

    return {
        "revenue": revenue,
        "operational_expenses": operational_expenses,
        "other_expenses": other_expenses,
        "invest_returns": invest_returns,
        "metadata": metadata,
        "report_settings": snapshot,
    }
