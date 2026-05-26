from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.payroll.models import PayrollDocument
from apps.modules.payroll.utils import tenant_has_payroll_module_enabled
from apps.modules.requests.models import Request
from apps.tenants.cash_expense_id_format import cash_expense_external_id_match_candidates
from apps.tenants.payroll_doc_id_format import payroll_doc_id_match_candidates


def _decimal_or_none(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _payroll_document_total(doc: PayrollDocument) -> Decimal:
    val = doc.lines.aggregate(s=Sum("sum")).get("s")
    return val if val is not None else Decimal("0")


def _filter_queryset_by_amount(qs, *, amount_field: str, amount_value: Decimal | None):
    if amount_value is None:
        return qs.none()
    return qs.filter(**{amount_field: amount_value})


def _single_match(qs, *, limit: int = 2):
    matches = list(qs[:limit])
    if len(matches) == 1:
        return matches[0]
    return None


def _normalize_expense_id_on_match(*, payment_type: str) -> bool:
    return payment_type in (Request.PAYMENT_TYPE_CASH, Request.PAYMENT_TYPE_PAYROLL)


def resolve_request_expense_ref(
    *,
    tenant,
    payment_type: str,
    category: str,
    expense_id_raw,
    expense_year,
    amount=None,
) -> tuple[int | None, str | None]:
    """
    Resolve business `expense_id` (+ context) to concrete expense PK and canonical `expense_id`.

    Amount must match the expense row (or payroll document total). Never raises: returns
    `(None, None)` if the row is missing, ambiguous, or inputs are insufficient.
    """
    raw = str(expense_id_raw or "").strip()
    if not raw:
        return None, None

    amount_value = _decimal_or_none(amount)

    if payment_type == Request.PAYMENT_TYPE_PAYROLL:
        if not tenant_has_payroll_module_enabled(tenant):
            return None, None
        candidates = payroll_doc_id_match_candidates(raw, tenant)
        qs = PayrollDocument.objects.filter(tenant=tenant, doc_id__in=candidates).order_by("-id")
        if amount_value is None:
            return None, None
        matching_docs = [doc for doc in qs[:5] if _payroll_document_total(doc) == amount_value]
        if len(matching_docs) == 1:
            match = matching_docs[0]
            normalized = str(match.doc_id or "").strip() or raw
            return match.id, normalized
        return None, None

    if payment_type == Request.PAYMENT_TYPE_CASH:
        candidates = cash_expense_external_id_match_candidates(raw, tenant)
        qs = CashExpense.objects.filter(tenant=tenant, external_id__in=candidates).order_by("-expense_year", "-id")
        if expense_year is not None:
            qs = qs.filter(expense_year=expense_year)
        qs = _filter_queryset_by_amount(qs, amount_field="amount", amount_value=amount_value)
        match = _single_match(qs)
        if match is None:
            return None, None
        normalized = str(match.external_id or "").strip() or raw
        return match.id, normalized

    if payment_type in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        if expense_year is None:
            return None, None
        qs = BankExpense.objects.filter(
            tenant=tenant,
            doc_no=raw,
            expense_year=expense_year,
        ).order_by("-doc_date", "-id")
        qs = _filter_queryset_by_amount(qs, amount_field="debit_turnover", amount_value=amount_value)
        match = _single_match(qs)
        if match is None:
            return None, None
        return match.id, raw

    if payment_type == Request.PAYMENT_TYPE_CARD:
        try:
            card_id = int(raw)
        except (TypeError, ValueError):
            return None, None
        qs = CardExpense.objects.filter(tenant=tenant, id=card_id)
        qs = _filter_queryset_by_amount(qs, amount_field="amount", amount_value=amount_value)
        match = _single_match(qs, limit=1)
        if match is None:
            return None, None
        return match.id, raw

    return None, None


def expense_ref_target_for(*, payment_type: str, category: str) -> str | None:
    if payment_type == Request.PAYMENT_TYPE_PAYROLL:
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
    amount=None,
) -> int | None:
    resolved_id, _normalized = resolve_request_expense_ref(
        tenant=tenant,
        payment_type=payment_type,
        category=category,
        expense_id_raw=expense_id_raw,
        expense_year=expense_year,
        amount=amount,
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
            amount=request_obj.amount,
        )
        if (
            normalized
            and _normalize_expense_id_on_match(payment_type=request_obj.payment_type)
            and request_obj.expense_id != normalized
        ):
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
