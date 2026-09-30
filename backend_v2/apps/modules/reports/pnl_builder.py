from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.models import InvestReturn
from apps.modules.investments.services import clamp_rate_date_to_cbu_availability, usd_uzs_equivalents_or_none
from apps.modules.requests.amortization import build_amortization_schedule_rows
from apps.modules.requests.models import Request, RequestPaymentPurposeConfig
from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.report_rules import (
    CFG_BANK_EXCLUDE,
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
    PAYMENT_TYPE_VALUES,
    ReportSettingsMissing,
    cash_operation_label,
    invest_type_bucket,
    iso_local,
    normalize_str_list,
    parse_start_month,
    purpose_bucket,
    request_author,
    rules_snapshot,
    validate_rules,
)


def _bank_purpose_excluded(purpose: str, patterns: list[str]) -> bool:
    """Bank statement payment_purpose is free text — match exclusion phrases as case-insensitive substrings."""
    text = purpose.strip().lower()
    if not text:
        return False
    return any(p.lower() in text for p in patterns)


def get_pnl_config_or_raise(*, tenant) -> dict[str, Any]:
    try:
        row = TenantReportSettings.objects.get(tenant_id=tenant.id)
    except TenantReportSettings.DoesNotExist as exc:
        raise ReportSettingsMissing(f"No tenant_report_settings for tenant_id={tenant.id}") from exc

    cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
    validate_rules(cfg)

    return cfg


def _parse_period_month(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        y, m, _day = text.split("-", 2)
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError):
        return None


def _invest_return_row(ir: InvestReturn) -> dict[str, Any] | None:
    """None, если курс ЦБ на дату выплаты недоступен (архив ещё не заполнен и сеть недоступна)."""
    rate_date = clamp_rate_date_to_cbu_availability(requested=ir.date)
    _, sum_uzs = usd_uzs_equivalents_or_none(sum_val=ir.sum, currency=ir.currency, rate_date=rate_date)
    if sum_uzs is None:
        return None
    label = ir.get_type_display()
    parts: list[str] = []
    if ir.comment and str(ir.comment).strip():
        parts.append(str(ir.comment).strip())
    parts.append(f"Получатель: {ir.get_recipient_display()}")
    description = " — ".join(parts) if len(parts) > 1 else parts[0]
    accrual = ir.billing_date
    accrual_day = date(accrual.year, accrual.month, 1)
    return {
        "id": str(ir.id),
        "date": accrual_day.isoformat(),
        "amount": str(sum_uzs),
        "category": label,
        "purpose": label,
        "description": description,
        "source": "invest_return",
    }


def _append_request_line(
    *,
    req: Request,
    bucket: str,
    report_start: date,
    operational_expenses: list[dict[str, Any]],
    other_expenses: list[dict[str, Any]],
    invest_returns: list[dict[str, Any]],
) -> None:
    cat = str(req.category or "").strip()
    purpose = str(req.payment_purpose or "").strip()
    base_item: dict[str, Any] = {
        "id": str(req.id),
        "amount": str(Decimal(req.amount)),
        "category": cat,
        "purpose": purpose,
        "description": str(req.description or ""),
        "source": "request",
        "request_id": str(req.id),
        "vendor": str(req.vendor or ""),
        "author": request_author(req),
    }
    target: list[dict[str, Any]]
    if bucket == "operational":
        target = operational_expenses
    elif bucket == "other":
        target = other_expenses
    else:
        target = invest_returns

    months = int(req.amortization_months or 1)
    if months < 2:
        if req.billing_date < report_start:
            return
        base_item["date"] = req.billing_date.isoformat()
        target.append(base_item)
        return

    for schedule_row in build_amortization_schedule_rows(req):
        period_month = _parse_period_month(str(schedule_row.get("period_month") or ""))
        if period_month is None or period_month < report_start:
            continue
        item = {
            **base_item,
            "amount": schedule_row["monthly_amount"],
            "date": schedule_row["period_month"],
            "period_index": int(schedule_row["period_index"]),
            "periods": months,
        }
        target.append(item)


def compute_unassigned_payment_purposes(*, tenant_id: int, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Distinct payment_purpose values on paid requests in PnL scope that appear in no purpose bucket."""
    validate_rules(cfg)
    start = parse_start_month(str(cfg[CFG_START_MONTH]))
    pay_list = [str(x).strip() for x in cfg[CFG_REQ_PAYMENT_TYPES] if str(x).strip() and str(x).strip() in PAYMENT_TYPE_VALUES]
    cat_exclude = {str(x).strip() for x in cfg[CFG_REQ_CAT_EXCLUDE] if str(x).strip()}
    op = set(normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP))
    ot = set(normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER))
    inv = set(normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV))
    assigned = op | ot | inv

    qs = Request.objects.filter(
        tenant_id=tenant_id,
        status=Request.STATUS_PAYED,
        billing_date__gte=start,
    )
    if pay_list:
        qs = qs.filter(payment_type__in=pay_list)
    else:
        qs = qs.none()

    rows = (
        qs.exclude(category__in=list(cat_exclude)) if cat_exclude else qs
    ).values("payment_purpose").annotate(c=Count("id"), s=Sum("amount"))

    out: list[dict[str, Any]] = []
    for row in rows:
        p = str(row["payment_purpose"] or "").strip()
        if not p or p in assigned:
            continue
        out.append({"purpose": p, "count": int(row["c"]), "amount": str(row["s"] or Decimal("0"))})
    out.sort(key=lambda x: (x["purpose"], -x["count"]))
    return out


def list_tenant_payment_purpose_pool(
    *,
    tenant_id: int,
    for_pnl_payment_types: list[str] | None = None,
) -> list[str]:
    """
    Names to offer in PnL settings: active purposes from the request form config
    plus any non-empty payment_purpose strings already used on requests for the tenant.

    When ``for_pnl_payment_types`` is set (including empty), only purposes tied to those
    payment types are included — aligned with ``request_payment_types_for_pnl`` in backend PnL.
    When ``None``, all payment types are considered (backward compatible API default).
    """

    merged: set[str] = set()

    purpose_qs = RequestPaymentPurposeConfig.objects.filter(
        payment_type_config__config__tenant_id=tenant_id,
        is_active=True,
    )
    req_qs = Request.objects.filter(tenant_id=tenant_id).exclude(payment_purpose="")

    if for_pnl_payment_types is not None:
        allowed = [
            str(x).strip()
            for x in for_pnl_payment_types
            if str(x).strip() and str(x).strip() in PAYMENT_TYPE_VALUES
        ]
        purpose_qs = purpose_qs.filter(payment_type_config__payment_type__in=allowed)
        if allowed:
            req_qs = req_qs.filter(payment_type__in=allowed)
        else:
            req_qs = req_qs.none()

    for name in purpose_qs.values_list("name", flat=True).iterator():
        s = str(name).strip()
        if s:
            merged.add(s)
    for p in req_qs.values_list("payment_purpose", flat=True).distinct().iterator():
        s = str(p).strip()
        if s:
            merged.add(s)
    return sorted(merged)


def build_pnl_payload_from_db(*, tenant, query_params: dict[str, Any]) -> dict[str, Any]:
    """
    Build raw PnL blocks from ORM (same logical shape as n8n webhook output before enrichment).
    """
    del query_params

    cfg = get_pnl_config_or_raise(tenant=tenant)
    start = parse_start_month(str(cfg[CFG_START_MONTH]))
    cash_exclude = {str(x).strip() for x in cfg[CFG_CASH_EXCLUDE] if str(x).strip()}
    bank_exclude = normalize_str_list(cfg.get(CFG_BANK_EXCLUDE, []), field=CFG_BANK_EXCLUDE)
    cat_exclude = {str(x).strip() for x in cfg[CFG_REQ_CAT_EXCLUDE] if str(x).strip()}
    pay_list = [str(x).strip() for x in cfg[CFG_REQ_PAYMENT_TYPES] if str(x).strip() in PAYMENT_TYPE_VALUES]

    purp_op = set(normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP))
    purp_ot = set(normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER))
    purp_inv = set(normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV))

    ir_op = set(normalize_str_list(cfg[CFG_IR_TYPE_OP], field=CFG_IR_TYPE_OP))
    ir_ot = set(normalize_str_list(cfg[CFG_IR_TYPE_OTHER], field=CFG_IR_TYPE_OTHER))
    ir_inv = set(normalize_str_list(cfg[CFG_IR_TYPE_INV], field=CFG_IR_TYPE_INV))

    snapshot = rules_snapshot(cfg)

    revenue: list[dict[str, Any]] = []

    for br in BankRevenue.objects.filter(tenant_id=tenant.id, doc_date__gte=start).order_by("doc_date", "id"):
        if _bank_purpose_excluded(str(br.payment_purpose or ""), bank_exclude):
            continue
        revenue.append(
            {
                "id": str(br.id),
                "date": br.doc_date.isoformat(),
                "amount": str(Decimal(br.kredit_turnover)),
                "category": "Поступление в банк",
                "purpose": "Поступление",
                "description": str(br.payment_purpose or ""),
                "source": "bank",
            }
        )

    cash_qs = CashRevenue.objects.filter(
        tenant_id=tenant.id,
        confirmed=True,
        revenue_at__date__gte=start,
    ).order_by("revenue_at", "id")
    for cr in cash_qs:
        op_label = cash_operation_label(cr)
        if op_label in cash_exclude:
            continue
        payload = cr.payload if isinstance(cr.payload, dict) else {}
        cat = str(payload.get("operation") or cr.operation or "").strip()
        revenue.append(
            {
                "id": str(cr.id),
                "date": iso_local(cr.revenue_at),
                "amount": str(Decimal(cr.total_sum)),
                "purpose": str(cr.operation or ""),
                "description": str(cr.counterparty or ""),
                "category": cat or "Без категории",
                "source": "cash",
            }
        )

    operational_expenses: list[dict[str, Any]] = []
    other_expenses: list[dict[str, Any]] = []
    invest_returns: list[dict[str, Any]] = []

    # Non-amortized: billing_date in report window. Amortized: all paid requests — schedule
    # may span years (manual values); rows outside start_month are dropped in _append_request_line.
    req_qs = Request.objects.filter(
        tenant_id=tenant.id,
        status=Request.STATUS_PAYED,
    ).filter(Q(billing_date__gte=start) | Q(amortization_months__gt=1))
    if pay_list:
        req_qs = req_qs.filter(payment_type__in=pay_list)
    else:
        req_qs = req_qs.none()

    for req in req_qs.select_related("requester").order_by("billing_date", "id"):
        cat = str(req.category or "").strip()
        if cat in cat_exclude:
            continue
        purpose = str(req.payment_purpose or "").strip()
        bucket = purpose_bucket(purpose, op=purp_op, ot=purp_ot, inv=purp_inv)
        if bucket is None:
            continue
        _append_request_line(
            req=req,
            bucket=bucket,
            report_start=start,
            operational_expenses=operational_expenses,
            other_expenses=other_expenses,
            invest_returns=invest_returns,
        )

    for ir in (
        InvestReturn.objects.filter(tenant_id=tenant.id, confirmed=True, billing_date__gte=start)
        .order_by("billing_date", "id")
    ):
        b = invest_type_bucket(str(ir.type or ""), op=ir_op, ot=ir_ot, inv=ir_inv)
        if b is None:
            continue
        row = _invest_return_row(ir)
        if row is None:
            continue
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
