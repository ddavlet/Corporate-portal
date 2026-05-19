from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.models import InvestReturn
from apps.modules.requests.models import Request
from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.pnl_builder import (
    CFG_CASH_EXCLUDE,
    CFG_IR_TYPE_INV,
    CFG_IR_TYPE_OP,
    CFG_IR_TYPE_OTHER,
    CFG_PURPOSE_INV,
    CFG_PURPOSE_OP,
    CFG_PURPOSE_OTHER,
    CFG_REQ_CAT_EXCLUDE,
    CFG_REQ_PAYMENT_TYPES,
    CFG_START_MONTH,
    ReportSettingsInvalid,
    ReportSettingsMissing,
    _cash_operation_label,
    _invest_type_bucket,
    _iso_local,
    _normalize_str_list,
    _parse_start_month,
    _purpose_bucket,
    _report_settings_snapshot,
    validate_pnl_config_dict,
)

_PAYMENT_TYPE_VALUES = frozenset(c[0] for c in Request.PAYMENT_TYPE_CHOICES)


def validate_cashflow_config_dict(cfg: dict[str, Any]) -> None:
    """Cashflow uses the same config shape as backend PnL."""
    validate_pnl_config_dict(cfg)


def get_cashflow_config_or_raise(*, tenant) -> dict[str, Any]:
    """Backend Cashflow reuses PnL filter config (pnl_config) — only expense dates differ."""
    try:
        row = TenantReportSettings.objects.get(tenant_id=tenant.id)
    except TenantReportSettings.DoesNotExist as exc:
        raise ReportSettingsMissing(f"No tenant_report_settings for tenant_id={tenant.id}") from exc

    cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
    validate_cashflow_config_dict(cfg)

    return cfg


def _start_month_as_ymd_int(start: date) -> int:
    return start.year * 10000 + start.month * 100 + 1


def _request_expense_period_filter(*, start: date) -> Q:
    """Paid requests whose cash expense date is on or after start month."""
    start_ymd = _start_month_as_ymd_int(start)
    by_expense_fields = Q(expense_year__isnull=False) & (
        Q(expense_year__gt=start.year) | Q(expense_year=start.year, expense_month__gte=start.month)
    )
    by_payed_at = Q(expense_year__isnull=True, payed_at__isnull=False, payed_at__gte=start_ymd)
    return by_expense_fields | by_payed_at


def _request_cash_expense_date(req: Request) -> date | None:
    y, m, d = req.expense_year, req.expense_month, req.expense_day
    if y is not None and m is not None:
        day = int(d) if d is not None else 1
        try:
            return date(int(y), int(m), day)
        except (TypeError, ValueError):
            pass
    if req.payed_at is not None:
        try:
            p = int(req.payed_at)
            return date(p // 10000, (p // 100) % 100, p % 100)
        except (TypeError, ValueError):
            pass
    return None


def _invest_return_cashflow_row(ir: InvestReturn) -> dict[str, Any]:
    label = ir.get_type_display()
    parts: list[str] = []
    if ir.comment and str(ir.comment).strip():
        parts.append(str(ir.comment).strip())
    parts.append(f"Получатель: {ir.get_recipient_display()}")
    description = " — ".join(parts) if len(parts) > 1 else parts[0]
    return {
        "id": str(ir.id),
        "date": ir.date.isoformat(),
        "amount": str(Decimal(ir.sum_uzs)),
        "category": label,
        "purpose": label,
        "description": description,
    }


def _append_request_line_cashflow(
    *,
    req: Request,
    bucket: str,
    operational_expenses: list[dict[str, Any]],
    other_expenses: list[dict[str, Any]],
    invest_returns: list[dict[str, Any]],
) -> None:
    expense_date = _request_cash_expense_date(req)
    if expense_date is None:
        return

    cat = str(req.category or "").strip()
    purpose = str(req.payment_purpose or "").strip()
    item: dict[str, Any] = {
        "id": str(req.id),
        "amount": str(Decimal(req.amount)),
        "date": expense_date.isoformat(),
        "category": cat,
        "purpose": purpose,
        "description": str(req.description or ""),
    }
    if bucket == "operational":
        operational_expenses.append(item)
    elif bucket == "other":
        other_expenses.append(item)
    else:
        invest_returns.append(item)


def compute_unassigned_payment_purposes_cashflow(*, tenant_id: int, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Distinct payment_purpose on paid requests in cashflow scope with no purpose bucket."""
    validate_cashflow_config_dict(cfg)
    start = _parse_start_month(str(cfg[CFG_START_MONTH]))
    pay_list = [
        str(x).strip()
        for x in cfg[CFG_REQ_PAYMENT_TYPES]
        if str(x).strip() and str(x).strip() in _PAYMENT_TYPE_VALUES
    ]
    cat_exclude = {str(x).strip() for x in cfg[CFG_REQ_CAT_EXCLUDE] if str(x).strip()}
    op = set(_normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP))
    ot = set(_normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER))
    inv = set(_normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV))
    assigned = op | ot | inv

    qs = Request.objects.filter(
        tenant_id=tenant_id,
        status=Request.STATUS_PAYED,
    ).filter(_request_expense_period_filter(start=start))
    if pay_list:
        qs = qs.filter(payment_type__in=pay_list)
    else:
        qs = qs.none()

    rows = (qs.exclude(category__in=list(cat_exclude)) if cat_exclude else qs).values("payment_purpose").annotate(
        c=Count("id")
    )

    out: list[dict[str, Any]] = []
    for row in rows:
        p = str(row["payment_purpose"] or "").strip()
        if not p or p in assigned:
            continue
        out.append({"purpose": p, "count": int(row["c"])})
    out.sort(key=lambda x: (x["purpose"], -x["count"]))
    return out


def build_cashflow_payload_from_db(*, tenant, query_params: dict[str, Any]) -> dict[str, Any]:
    """
    Build raw Cashflow blocks from ORM (same logical shape as n8n webhook output before enrichment).
    Revenue matches backend PnL; expenses use cash payment dates without amortization.
    """
    del query_params

    cfg = get_cashflow_config_or_raise(tenant=tenant)
    start = _parse_start_month(str(cfg[CFG_START_MONTH]))
    cash_exclude = {str(x).strip() for x in cfg[CFG_CASH_EXCLUDE] if str(x).strip()}
    cat_exclude = {str(x).strip() for x in cfg[CFG_REQ_CAT_EXCLUDE] if str(x).strip()}
    pay_list = [str(x).strip() for x in cfg[CFG_REQ_PAYMENT_TYPES] if str(x).strip() in _PAYMENT_TYPE_VALUES]

    purp_op = set(_normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP))
    purp_ot = set(_normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER))
    purp_inv = set(_normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV))

    ir_op = set(_normalize_str_list(cfg[CFG_IR_TYPE_OP], field=CFG_IR_TYPE_OP))
    ir_ot = set(_normalize_str_list(cfg[CFG_IR_TYPE_OTHER], field=CFG_IR_TYPE_OTHER))
    ir_inv = set(_normalize_str_list(cfg[CFG_IR_TYPE_INV], field=CFG_IR_TYPE_INV))

    snapshot = _report_settings_snapshot(cfg)

    revenue: list[dict[str, Any]] = []

    for br in BankRevenue.objects.filter(tenant_id=tenant.id, doc_date__gte=start).order_by("doc_date", "id"):
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

    cash_qs = CashRevenue.objects.filter(
        tenant_id=tenant.id,
        confirmed=True,
        revenue_at__date__gte=start,
    ).order_by("revenue_at", "id")
    for cr in cash_qs:
        op_label = _cash_operation_label(cr)
        if op_label in cash_exclude:
            continue
        payload = cr.payload if isinstance(cr.payload, dict) else {}
        cat = str(payload.get("operation") or cr.operation or "").strip()
        revenue.append(
            {
                "id": str(cr.id),
                "date": _iso_local(cr.revenue_at),
                "amount": str(Decimal(cr.total_sum)),
                "purpose": str(cr.operation or ""),
                "description": str(cr.counterparty or ""),
                "category": cat or "Без категории",
            }
        )

    operational_expenses: list[dict[str, Any]] = []
    other_expenses: list[dict[str, Any]] = []
    invest_returns: list[dict[str, Any]] = []

    req_qs = Request.objects.filter(
        tenant_id=tenant.id,
        status=Request.STATUS_PAYED,
    ).filter(_request_expense_period_filter(start=start))
    if pay_list:
        req_qs = req_qs.filter(payment_type__in=pay_list)
    else:
        req_qs = req_qs.none()

    for req in req_qs.order_by("expense_year", "expense_month", "expense_day", "id"):
        cat = str(req.category or "").strip()
        if cat in cat_exclude:
            continue
        purpose = str(req.payment_purpose or "").strip()
        bucket = _purpose_bucket(purpose, op=purp_op, ot=purp_ot, inv=purp_inv)
        if bucket is None:
            continue
        _append_request_line_cashflow(
            req=req,
            bucket=bucket,
            operational_expenses=operational_expenses,
            other_expenses=other_expenses,
            invest_returns=invest_returns,
        )

    for ir in (
        InvestReturn.objects.filter(tenant_id=tenant.id, confirmed=True, date__gte=start)
        .exclude(sum_uzs__isnull=True)
        .order_by("date", "id")
    ):
        b = _invest_type_bucket(str(ir.type or ""), op=ir_op, ot=ir_ot, inv=ir_inv)
        if b is None:
            continue
        row = _invest_return_cashflow_row(ir)
        if b == "operational":
            operational_expenses.append(row)
        elif b == "other":
            other_expenses.append(row)
        else:
            invest_returns.append(row)

    metadata = {
        CFG_START_MONTH: str(cfg[CFG_START_MONTH]).strip(),
    }

    return {
        "revenue": revenue,
        "operational_expenses": operational_expenses,
        "other_expenses": other_expenses,
        "invest_returns": invest_returns,
        "metadata": metadata,
        "report_settings": snapshot,
    }
