from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.models import InvestReturn
from apps.modules.requests.amortization import build_amortization_schedule_rows
from apps.modules.requests.models import Request, RequestPaymentPurposeConfig
from apps.modules.reports.models import TenantReportSettings

# --- pnl_config keys (backend PnL) ---
CFG_START_MONTH = "start_month"
CFG_CASH_EXCLUDE = "cash_exclude_operations"
CFG_REQ_CAT_EXCLUDE = "request_exclude_categories"
CFG_REQ_PAYMENT_TYPES = "request_payment_types_for_pnl"
CFG_PURPOSE_OP = "payment_purpose_operational"
CFG_PURPOSE_OTHER = "payment_purpose_other"
CFG_PURPOSE_INV = "payment_purpose_invest_returns"
CFG_IR_TYPE_OP = "invest_return_type_operational"
CFG_IR_TYPE_OTHER = "invest_return_type_other"
CFG_IR_TYPE_INV = "invest_return_type_invest_returns"
CFG_OPENING_BALANCE = "opening_balance"

_PAYMENT_TYPE_VALUES = frozenset(c[0] for c in Request.PAYMENT_TYPE_CHOICES)
_RETURN_TYPE_VALUES = frozenset(c[0] for c in InvestReturn.ReturnType.choices)


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


def _parse_opening_balance(raw: Any) -> Decimal:
    """Cash balance at the beginning of ``start_month`` (before flows in that month). Defaults to 0."""
    if raw is None:
        return Decimal("0")
    text = str(raw).strip().replace(" ", "").replace(",", ".")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ReportSettingsInvalid(f"Invalid opening_balance {raw!r}, expected a decimal number.") from exc


def _iso_local(dt: datetime | date | None) -> str:
    if dt is None:
        return ""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, datetime):
        tz = timezone.get_default_timezone()
        if settings.USE_TZ and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, tz)
        local = timezone.localtime(dt, timezone=tz) if settings.USE_TZ else dt
        return local.isoformat()
    return ""


def _cash_operation_label(row: CashRevenue) -> str:
    payload = row.payload if isinstance(row.payload, dict) else {}
    op = payload.get("operation")
    if op is not None and str(op).strip():
        return str(op).strip()
    return str(row.operation or "").strip()


def _normalize_str_list(raw: Any, *, field: str) -> list[str]:
    if not isinstance(raw, list):
        raise ReportSettingsInvalid(f"{field} must be a list")
    seen: set[str] = set()
    out: list[str] = []
    for x in raw:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _validate_disjoint_string_sets(
    *,
    a: list[str],
    b: list[str],
    c: list[str],
    label: str,
) -> None:
    sa, sb, sc = set(a), set(b), set(c)
    if sa & sb:
        raise ReportSettingsInvalid(f"{label}: overlap between operational and other.")
    if sa & sc:
        raise ReportSettingsInvalid(f"{label}: overlap between operational and invest_returns bucket.")
    if sb & sc:
        raise ReportSettingsInvalid(f"{label}: overlap between other and invest_returns bucket.")


def validate_pnl_config_dict(cfg: dict[str, Any]) -> None:
    """Raise ReportSettingsInvalid if cfg cannot drive backend PnL."""
    required = (
        CFG_START_MONTH,
        CFG_CASH_EXCLUDE,
        CFG_REQ_CAT_EXCLUDE,
        CFG_REQ_PAYMENT_TYPES,
        CFG_PURPOSE_OP,
        CFG_PURPOSE_OTHER,
        CFG_PURPOSE_INV,
        CFG_IR_TYPE_OP,
        CFG_IR_TYPE_OTHER,
        CFG_IR_TYPE_INV,
    )
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ReportSettingsInvalid(f"pnl_config missing keys: {missing}")

    _parse_start_month(str(cfg[CFG_START_MONTH]))

    _normalize_str_list(cfg[CFG_CASH_EXCLUDE], field=CFG_CASH_EXCLUDE)
    _normalize_str_list(cfg[CFG_REQ_CAT_EXCLUDE], field=CFG_REQ_CAT_EXCLUDE)

    pay_types_in = cfg[CFG_REQ_PAYMENT_TYPES]
    if not isinstance(pay_types_in, list):
        raise ReportSettingsInvalid(f"{CFG_REQ_PAYMENT_TYPES} must be a list")
    payment_types: list[str] = []
    seen_pt: set[str] = set()
    for x in pay_types_in:
        s = str(x).strip()
        if not s:
            continue
        if s not in _PAYMENT_TYPE_VALUES:
            raise ReportSettingsInvalid(
                f"{CFG_REQ_PAYMENT_TYPES} contains invalid value {s!r}; "
                f"allowed: {sorted(_PAYMENT_TYPE_VALUES)}"
            )
        if s not in seen_pt:
            seen_pt.add(s)
            payment_types.append(s)

    purp_op = _normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP)
    purp_ot = _normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER)
    purp_inv = _normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV)
    _validate_disjoint_string_sets(a=purp_op, b=purp_ot, c=purp_inv, label="payment_purpose_*")

    ir_op = _normalize_str_list(cfg[CFG_IR_TYPE_OP], field=CFG_IR_TYPE_OP)
    ir_ot = _normalize_str_list(cfg[CFG_IR_TYPE_OTHER], field=CFG_IR_TYPE_OTHER)
    ir_inv = _normalize_str_list(cfg[CFG_IR_TYPE_INV], field=CFG_IR_TYPE_INV)
    for label, lst in (
        (CFG_IR_TYPE_OP, ir_op),
        (CFG_IR_TYPE_OTHER, ir_ot),
        (CFG_IR_TYPE_INV, ir_inv),
    ):
        for x in lst:
            if x not in _RETURN_TYPE_VALUES:
                raise ReportSettingsInvalid(f"{label} contains invalid invest return type {x!r}.")
    _validate_disjoint_string_sets(a=ir_op, b=ir_ot, c=ir_inv, label="invest_return_type_*")

    union_ir = set(ir_op) | set(ir_ot) | set(ir_inv)
    if union_ir != _RETURN_TYPE_VALUES:
        raise ReportSettingsInvalid(
            "invest_return_type_* must partition ReturnType exactly once each; "
            f"expected {_sorted_return_types()}, got union={sorted(union_ir)}"
        )
    if len(ir_op) + len(ir_ot) + len(ir_inv) != len(_RETURN_TYPE_VALUES):
        raise ReportSettingsInvalid("invest_return_type_* lists must not contain duplicates across buckets.")

    if CFG_OPENING_BALANCE in cfg:
        _parse_opening_balance(cfg.get(CFG_OPENING_BALANCE))


def _sorted_return_types() -> list[str]:
    return sorted(_RETURN_TYPE_VALUES)


def get_pnl_config_or_raise(*, tenant) -> dict[str, Any]:
    try:
        row = TenantReportSettings.objects.get(tenant_id=tenant.id)
    except TenantReportSettings.DoesNotExist as exc:
        raise ReportSettingsMissing(f"No tenant_report_settings for tenant_id={tenant.id}") from exc

    cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
    validate_pnl_config_dict(cfg)

    return cfg


def _report_settings_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    cash_exclude = {str(x).strip() for x in cfg[CFG_CASH_EXCLUDE] if str(x).strip()}
    cat_exclude = {str(x).strip() for x in cfg[CFG_REQ_CAT_EXCLUDE] if str(x).strip()}
    pay_types: list[str] = []
    seen: set[str] = set()
    for x in cfg[CFG_REQ_PAYMENT_TYPES]:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            pay_types.append(s)
    opening = _parse_opening_balance(cfg.get(CFG_OPENING_BALANCE))

    return {
        CFG_START_MONTH: str(cfg[CFG_START_MONTH]).strip(),
        CFG_CASH_EXCLUDE: sorted(cash_exclude),
        CFG_REQ_CAT_EXCLUDE: sorted(cat_exclude),
        CFG_REQ_PAYMENT_TYPES: pay_types,
        CFG_PURPOSE_OP: sorted(_normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP)),
        CFG_PURPOSE_OTHER: sorted(_normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER)),
        CFG_PURPOSE_INV: sorted(_normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV)),
        CFG_IR_TYPE_OP: sorted(_normalize_str_list(cfg[CFG_IR_TYPE_OP], field=CFG_IR_TYPE_OP)),
        CFG_IR_TYPE_OTHER: sorted(_normalize_str_list(cfg[CFG_IR_TYPE_OTHER], field=CFG_IR_TYPE_OTHER)),
        CFG_IR_TYPE_INV: sorted(_normalize_str_list(cfg[CFG_IR_TYPE_INV], field=CFG_IR_TYPE_INV)),
        CFG_OPENING_BALANCE: str(opening),
    }


def _purpose_bucket(purpose: str, *, op: set[str], ot: set[str], inv: set[str]) -> str | None:
    p = purpose.strip()
    if p in op:
        return "operational"
    if p in ot:
        return "other"
    if p in inv:
        return "invest_returns"
    return None


def _invest_type_bucket(type_value: str, *, op: set[str], ot: set[str], inv: set[str]) -> str | None:
    t = type_value.strip()
    if t in op:
        return "operational"
    if t in ot:
        return "other"
    if t in inv:
        return "invest_returns"
    return None


def _parse_period_month(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        y, m, _day = text.split("-", 2)
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError):
        return None


def _invest_return_row(ir: InvestReturn) -> dict[str, Any]:
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
        "amount": str(Decimal(ir.sum_uzs)),
        "category": label,
        "purpose": label,
        "description": description,
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
        }
        target.append(item)


def compute_unassigned_payment_purposes(*, tenant_id: int, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Distinct payment_purpose values on paid requests in PnL scope that appear in no purpose bucket."""
    validate_pnl_config_dict(cfg)
    start = _parse_start_month(str(cfg[CFG_START_MONTH]))
    pay_list = [str(x).strip() for x in cfg[CFG_REQ_PAYMENT_TYPES] if str(x).strip() and str(x).strip() in _PAYMENT_TYPE_VALUES]
    cat_exclude = {str(x).strip() for x in cfg[CFG_REQ_CAT_EXCLUDE] if str(x).strip()}
    op = set(_normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP))
    ot = set(_normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER))
    inv = set(_normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV))
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
    ).values("payment_purpose").annotate(c=Count("id"))

    out: list[dict[str, Any]] = []
    for row in rows:
        p = str(row["payment_purpose"] or "").strip()
        if not p or p in assigned:
            continue
        out.append({"purpose": p, "count": int(row["c"])})
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
            if str(x).strip() and str(x).strip() in _PAYMENT_TYPE_VALUES
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

    for req in req_qs.order_by("billing_date", "id"):
        cat = str(req.category or "").strip()
        if cat in cat_exclude:
            continue
        purpose = str(req.payment_purpose or "").strip()
        bucket = _purpose_bucket(purpose, op=purp_op, ot=purp_ot, inv=purp_inv)
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
        .exclude(sum_uzs__isnull=True)
        .order_by("billing_date", "id")
    ):
        b = _invest_type_bucket(str(ir.type or ""), op=ir_op, ot=ir_ot, inv=ir_inv)
        if b is None:
            continue
        row = _invest_return_row(ir)
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
