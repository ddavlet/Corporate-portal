"""Calculation rules shared by every report, and the helpers both report builders use to apply them.

PnL keeps its rules in ``pnl_config`` and Cashflow in ``cashflow_config``; the keys and their validation are
the same. ``bank_exclude_purposes`` is optional and only the PnL builder applies it.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.models import InvestReturn
from apps.modules.requests.models import Request

# --- rule keys (pnl_config / cashflow_config) ---
CFG_START_MONTH = "start_month"
CFG_CASH_EXCLUDE = "cash_exclude_operations"
CFG_BANK_EXCLUDE = "bank_exclude_purposes"
CFG_REQ_CAT_EXCLUDE = "request_exclude_categories"
CFG_REQ_PAYMENT_TYPES = "request_payment_types_for_pnl"
CFG_PURPOSE_OP = "payment_purpose_operational"
CFG_PURPOSE_OTHER = "payment_purpose_other"
CFG_PURPOSE_INV = "payment_purpose_invest_returns"
CFG_IR_TYPE_OP = "invest_return_type_operational"
CFG_IR_TYPE_OTHER = "invest_return_type_other"
CFG_IR_TYPE_INV = "invest_return_type_invest_returns"
CFG_OPENING_BALANCE = "opening_balance"

PAYMENT_TYPE_VALUES = frozenset(c[0] for c in Request.PAYMENT_TYPE_CHOICES)
RETURN_TYPE_VALUES = frozenset(c[0] for c in InvestReturn.ReturnType.choices)


class ReportSettingsMissing(Exception):
    """No TenantReportSettings row for tenant."""


class ReportSettingsInvalid(Exception):
    """Report rules are missing required keys or have invalid values."""


def parse_start_month(value: str) -> date:
    text = (value or "").strip()
    try:
        y, m = text.split("-", 1)
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError) as exc:
        raise ReportSettingsInvalid(f"Invalid start_month {value!r}, expected YYYY-MM.") from exc


def parse_opening_balance(raw: Any) -> Decimal:
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


def iso_local(dt: datetime | date | None) -> str:
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


def cash_operation_label(row: CashRevenue) -> str:
    payload = row.payload if isinstance(row.payload, dict) else {}
    op = payload.get("operation")
    if op is not None and str(op).strip():
        return str(op).strip()
    return str(row.operation or "").strip()


def normalize_str_list(raw: Any, *, field: str) -> list[str]:
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


def validate_rules(cfg: dict[str, Any]) -> None:
    """Raise ReportSettingsInvalid if cfg cannot drive a report built in the application (PnL or Cashflow)."""
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
        raise ReportSettingsInvalid(f"rules missing keys: {missing}")

    parse_start_month(str(cfg[CFG_START_MONTH]))

    normalize_str_list(cfg[CFG_CASH_EXCLUDE], field=CFG_CASH_EXCLUDE)
    normalize_str_list(cfg[CFG_REQ_CAT_EXCLUDE], field=CFG_REQ_CAT_EXCLUDE)

    pay_types_in = cfg[CFG_REQ_PAYMENT_TYPES]
    if not isinstance(pay_types_in, list):
        raise ReportSettingsInvalid(f"{CFG_REQ_PAYMENT_TYPES} must be a list")
    payment_types: list[str] = []
    seen_pt: set[str] = set()
    for x in pay_types_in:
        s = str(x).strip()
        if not s:
            continue
        if s not in PAYMENT_TYPE_VALUES:
            raise ReportSettingsInvalid(
                f"{CFG_REQ_PAYMENT_TYPES} contains invalid value {s!r}; "
                f"allowed: {sorted(PAYMENT_TYPE_VALUES)}"
            )
        if s not in seen_pt:
            seen_pt.add(s)
            payment_types.append(s)

    purp_op = normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP)
    purp_ot = normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER)
    purp_inv = normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV)
    _validate_disjoint_string_sets(a=purp_op, b=purp_ot, c=purp_inv, label="payment_purpose_*")

    ir_op = normalize_str_list(cfg[CFG_IR_TYPE_OP], field=CFG_IR_TYPE_OP)
    ir_ot = normalize_str_list(cfg[CFG_IR_TYPE_OTHER], field=CFG_IR_TYPE_OTHER)
    ir_inv = normalize_str_list(cfg[CFG_IR_TYPE_INV], field=CFG_IR_TYPE_INV)
    for label, lst in (
        (CFG_IR_TYPE_OP, ir_op),
        (CFG_IR_TYPE_OTHER, ir_ot),
        (CFG_IR_TYPE_INV, ir_inv),
    ):
        for x in lst:
            if x not in RETURN_TYPE_VALUES:
                raise ReportSettingsInvalid(f"{label} contains invalid invest return type {x!r}.")
    _validate_disjoint_string_sets(a=ir_op, b=ir_ot, c=ir_inv, label="invest_return_type_*")

    union_ir = set(ir_op) | set(ir_ot) | set(ir_inv)
    if union_ir != RETURN_TYPE_VALUES:
        raise ReportSettingsInvalid(
            "invest_return_type_* must partition ReturnType exactly once each; "
            f"expected {_sorted_return_types()}, got union={sorted(union_ir)}"
        )
    if len(ir_op) + len(ir_ot) + len(ir_inv) != len(RETURN_TYPE_VALUES):
        raise ReportSettingsInvalid("invest_return_type_* lists must not contain duplicates across buckets.")

    if CFG_OPENING_BALANCE in cfg:
        parse_opening_balance(cfg.get(CFG_OPENING_BALANCE))

    # Optional key: absent in rules saved before bank exclusions existed, and in Cashflow rules.
    if CFG_BANK_EXCLUDE in cfg:
        normalize_str_list(cfg[CFG_BANK_EXCLUDE], field=CFG_BANK_EXCLUDE)


def _sorted_return_types() -> list[str]:
    return sorted(RETURN_TYPE_VALUES)


def rules_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    """The rules a payload was built with (``report_settings``), for the report page and «Как считается»."""
    cash_exclude = {str(x).strip() for x in cfg[CFG_CASH_EXCLUDE] if str(x).strip()}
    cat_exclude = {str(x).strip() for x in cfg[CFG_REQ_CAT_EXCLUDE] if str(x).strip()}
    pay_types: list[str] = []
    seen: set[str] = set()
    for x in cfg[CFG_REQ_PAYMENT_TYPES]:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            pay_types.append(s)
    opening = parse_opening_balance(cfg.get(CFG_OPENING_BALANCE))

    bank_exclude = normalize_str_list(cfg.get(CFG_BANK_EXCLUDE, []), field=CFG_BANK_EXCLUDE)

    return {
        CFG_START_MONTH: str(cfg[CFG_START_MONTH]).strip(),
        CFG_CASH_EXCLUDE: sorted(cash_exclude),
        CFG_BANK_EXCLUDE: sorted(bank_exclude),
        CFG_REQ_CAT_EXCLUDE: sorted(cat_exclude),
        CFG_REQ_PAYMENT_TYPES: pay_types,
        CFG_PURPOSE_OP: sorted(normalize_str_list(cfg[CFG_PURPOSE_OP], field=CFG_PURPOSE_OP)),
        CFG_PURPOSE_OTHER: sorted(normalize_str_list(cfg[CFG_PURPOSE_OTHER], field=CFG_PURPOSE_OTHER)),
        CFG_PURPOSE_INV: sorted(normalize_str_list(cfg[CFG_PURPOSE_INV], field=CFG_PURPOSE_INV)),
        CFG_IR_TYPE_OP: sorted(normalize_str_list(cfg[CFG_IR_TYPE_OP], field=CFG_IR_TYPE_OP)),
        CFG_IR_TYPE_OTHER: sorted(normalize_str_list(cfg[CFG_IR_TYPE_OTHER], field=CFG_IR_TYPE_OTHER)),
        CFG_IR_TYPE_INV: sorted(normalize_str_list(cfg[CFG_IR_TYPE_INV], field=CFG_IR_TYPE_INV)),
        CFG_OPENING_BALANCE: str(opening),
    }


def purpose_bucket(purpose: str, *, op: set[str], ot: set[str], inv: set[str]) -> str | None:
    p = purpose.strip()
    if p in op:
        return "operational"
    if p in ot:
        return "other"
    if p in inv:
        return "invest_returns"
    return None


def invest_type_bucket(type_value: str, *, op: set[str], ot: set[str], inv: set[str]) -> str | None:
    t = type_value.strip()
    if t in op:
        return "operational"
    if t in ot:
        return "other"
    if t in inv:
        return "invest_returns"
    return None


def request_author(req: Request) -> str:
    """Who asked for the money: full name, or the login when the profile has no name."""
    user = req.requester
    if user is None:
        return ""
    return (user.get_full_name() or user.username or "").strip()
