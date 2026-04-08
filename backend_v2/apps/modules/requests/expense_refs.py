from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.payroll.constants import SALARY_CATEGORY
from apps.modules.payroll.models import PayrollDocument
from apps.modules.payroll.utils import tenant_has_payroll_module_enabled
from apps.modules.requests.models import Request


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
    """
    Best-effort resolve business `expense_id` (+ context) to a concrete expense PK.
    Never raises: returns None if the row is missing, ambiguous, or inputs are insufficient.
    """
    raw = str(expense_id_raw or "").strip()
    if not raw:
        return None

    if payment_type == Request.PAYMENT_TYPE_CASH and (category or "").strip() == SALARY_CATEGORY:
        if not tenant_has_payroll_module_enabled(tenant):
            return None
        payroll_doc = PayrollDocument.objects.filter(tenant=tenant, doc_id=raw).first()
        return payroll_doc.id if payroll_doc else None

    if payment_type == Request.PAYMENT_TYPE_CASH:
        qs = CashExpense.objects.filter(tenant=tenant, external_id=raw).order_by("-expense_year", "-id")
        if expense_year is not None:
            qs = qs.filter(expense_year=expense_year)
        matches = list(qs[:2])
        if len(matches) == 1:
            return matches[0].id
        return None

    if payment_type in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        if expense_year is None:
            return None
        qs = BankExpense.objects.filter(
            tenant=tenant,
            doc_no=raw,
            expense_year=expense_year,
        ).order_by("-doc_date", "-id")
        matches = list(qs[:2])
        if len(matches) == 1:
            return matches[0].id
        return None

    if payment_type == Request.PAYMENT_TYPE_CARD:
        try:
            card_id = int(raw)
        except (TypeError, ValueError):
            return None
        if CardExpense.objects.filter(tenant=tenant, id=card_id).exists():
            return card_id
        return None

    return None


def maybe_persist_request_expense_ref(*, request_obj: Request, tenant) -> int | None:
    """
    Try resolve from current `expense_id` / context; if found, persist `expense_ref_id`
    and `expense_ref_target`. Multiple requests may reference the same expense row.
    """
    raw = str(request_obj.expense_id or "").strip()
    resolved: int | None = None
    if raw:
        resolved = try_resolve_request_expense_ref_id(
            tenant=tenant,
            payment_type=request_obj.payment_type,
            category=request_obj.category,
            expense_id_raw=raw,
            expense_year=request_obj.expense_year,
        )
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
