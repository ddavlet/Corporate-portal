from __future__ import annotations

from typing import Any

from apps.modules.requests.models import Request, RequestApprovalPaymentTypeConfig


RULE_OPERATOR_EQ = "eq"

RULE_FIELD_OPTIONS: dict[str, tuple[str, ...]] = {
    Request.PAYMENT_TYPE_CASH: ("title",),
    Request.PAYMENT_TYPE_TRANSFER: ("payment_purpose", "category", "vendor"),
    Request.PAYMENT_TYPE_TOPUP: ("payment_purpose", "category", "vendor"),
    Request.PAYMENT_TYPE_CARD: ("payment_purpose", "category"),
}


def request_not_required_field_options_for_payment_type(payment_type: str) -> list[str]:
    return list(RULE_FIELD_OPTIONS.get(payment_type, ()))


def is_request_required_for_expense(*, tenant, payment_type: str, expense_obj: Any) -> bool:
    """
    Request is required by default.
    It becomes not required when at least one tenant rule matches the expense row.
    """
    pt_cfg = (
        RequestApprovalPaymentTypeConfig.objects.filter(
            config__tenant=tenant,
            payment_type=payment_type,
        )
        .order_by("id")
        .first()
    )
    if not pt_cfg:
        return True
    rules = pt_cfg.request_not_required_rules or []
    if not isinstance(rules, list):
        return True
    allowed_fields = set(RULE_FIELD_OPTIONS.get(payment_type, ()))
    for rule in rules:
        if not _rule_matches_expense(rule=rule, expense_obj=expense_obj, allowed_fields=allowed_fields):
            continue
        return False
    return True


def _rule_matches_expense(*, rule: Any, expense_obj: Any, allowed_fields: set[str]) -> bool:
    if not isinstance(rule, dict):
        return False
    field = str(rule.get("field") or "").strip()
    operator = str(rule.get("operator") or RULE_OPERATOR_EQ).strip().lower()
    value = str(rule.get("value") or "").strip()
    if not field or not value:
        return False
    if field not in allowed_fields:
        return False
    if operator != RULE_OPERATOR_EQ:
        return False

    actual_raw = _extract_expense_field_value(expense_obj=expense_obj, field=field)
    actual = str(actual_raw if actual_raw is not None else "").strip()
    return actual == value


def _extract_expense_field_value(*, expense_obj: Any, field: str) -> Any:
    payload = getattr(expense_obj, "payload", None)
    payload_obj = payload if isinstance(payload, dict) else {}
    if field == "payment_purpose":
        if getattr(expense_obj, "payment_purpose", None) is not None:
            return getattr(expense_obj, "payment_purpose")
        return payload_obj.get("payment_purpose") or payload_obj.get("purpose")
    if field == "category":
        return (
            payload_obj.get("category")
            or payload_obj.get("cathegory")
            or payload_obj.get("cat")
            or payload_obj.get("cat_name")
        )
    if field == "vendor":
        vendor = getattr(expense_obj, "vendor", None)
        return getattr(vendor, "name", None)
    return getattr(expense_obj, field, None)
