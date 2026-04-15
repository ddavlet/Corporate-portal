from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.payroll.constants import SALARY_CATEGORY
from apps.modules.payroll.models import PayrollDocument
from apps.modules.payroll.utils import tenant_has_payroll_module_enabled
from apps.modules.requests.models import Request


def _cash_external_id_candidates(raw: str) -> list[str]:
    """
    Build candidate IDs for cash expense matching.

    Supports both plain numeric IDs (`343`) and canonical cash IDs (`1-000000343`).
    """
    value = str(raw or "").strip()
    if not value:
        return []

    candidates: list[str] = [value]
    numeric_part: str | None = None
    if value.isdigit():
        numeric_part = value
    elif value.startswith("1-"):
        suffix = value[2:]
        if suffix.isdigit():
            numeric_part = str(int(suffix))

    if numeric_part is not None:
        plain = str(int(numeric_part))
        canonical = f"1-{int(numeric_part):09d}"
        for candidate in (plain, canonical):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def resolve_request_expense_ref(
    *,
    tenant,
    payment_type: str,
    category: str,
    expense_id_raw,
    expense_year,
) -> tuple[int | None, str | None]:
    """
    Resolve business `expense_id` (+ context) to concrete expense PK and canonical `expense_id`.

    Never raises: returns `(None, None)` if the row is missing, ambiguous, or inputs are insufficient.
    """
    raw = str(expense_id_raw or "").strip()
    if not raw:
        return None, None

    if payment_type == Request.PAYMENT_TYPE_CASH and (category or "").strip() == SALARY_CATEGORY:
        if not tenant_has_payroll_module_enabled(tenant):
            return None, None
        payroll_doc = PayrollDocument.objects.filter(tenant=tenant, doc_id=raw).first()
        if not payroll_doc:
            return None, None
        return payroll_doc.id, str(payroll_doc.doc_id or "").strip() or raw

    if payment_type == Request.PAYMENT_TYPE_CASH:
        candidates = _cash_external_id_candidates(raw)
        qs = CashExpense.objects.filter(tenant=tenant, external_id__in=candidates).order_by("-expense_year", "-id")
        if expense_year is not None:
            qs = qs.filter(expense_year=expense_year)
        matches = list(qs[:2])
        if len(matches) == 1:
            match = matches[0]
            normalized = str(match.external_id or "").strip() or raw
            return match.id, normalized
        return None, None

    if payment_type in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        if expense_year is None:
            return None, None
        qs = BankExpense.objects.filter(
            tenant=tenant,
            doc_no=raw,
            expense_year=expense_year,
        ).order_by("-doc_date", "-id")
        matches = list(qs[:2])
        if len(matches) == 1:
            return matches[0].id, raw
        return None, None

    if payment_type == Request.PAYMENT_TYPE_CARD:
        try:
            card_id = int(raw)
        except (TypeError, ValueError):
            return None, None
        if CardExpense.objects.filter(tenant=tenant, id=card_id).exists():
            return card_id, raw
        return None, None

    return None, None


def expense_ref_target_for(*, payment_type: str, category: str) -> str | None:
    if payment_type == Request.PAYMENT_TYPE_CASH and (category or "").strip() == SALARY_CATEGORY:
        return Request.EXPENSE_REF_TARGET_PAYROLL
    if payment_type == Request.PAYMENT_TYPE_CASH:
        return Request.EXPENSE_REF_TARGET_CASH
    if payment_type in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        return Request.EXPENSE_REF_TARGET_BANK
    if payment_type == Request.PAYMENT_TYPE_CARD:
        return Request.EXPENSE_REF_TARGET_CARD
    return None


def try_resolve_request_expense_ref_id(
    *,
    tenant,
    payment_type: str,
    category: str,
    expense_id_raw,
    expense_year,
) -> int | None:
    resolved_id, _normalized = resolve_request_expense_ref(
        tenant=tenant,
        payment_type=payment_type,
        category=category,
        expense_id_raw=expense_id_raw,
        expense_year=expense_year,
    )
    return resolved_id


def maybe_persist_request_expense_ref(*, request_obj: Request, tenant) -> int | None:
    """
    Try resolve from current `expense_id` / context; if found, persist `expense_ref_id`
    and `expense_ref_target`. Multiple requests may reference the same expense row.
    """
    raw = str(request_obj.expense_id or "").strip()
    resolved: int | None = None
    if raw:
        resolved, normalized = resolve_request_expense_ref(
            tenant=tenant,
            payment_type=request_obj.payment_type,
            category=request_obj.category,
            expense_id_raw=raw,
            expense_year=request_obj.expense_year,
        )
        if normalized and request_obj.payment_type == Request.PAYMENT_TYPE_CASH and request_obj.expense_id != normalized:
            Request.objects.filter(pk=request_obj.pk, tenant_id=tenant.id).update(expense_id=normalized)
            request_obj.expense_id = normalized
    target = expense_ref_target_for(
        payment_type=request_obj.payment_type,
        category=request_obj.category,
    )

    if resolved is not None and target:
        if request_obj.expense_ref_id != resolved or request_obj.expense_ref_target != target:
            Request.objects.filter(pk=request_obj.pk, tenant_id=tenant.id).update(
                expense_ref_id=resolved,
                expense_ref_target=target,
            )
            request_obj.expense_ref_id = resolved
            request_obj.expense_ref_target = target
        return resolved

    return request_obj.expense_ref_id or None
