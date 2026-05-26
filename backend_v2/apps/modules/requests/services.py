from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.payroll.models import PayrollDocument
from apps.modules.requests.models import Request, RequestPaymentPurposeConfig
from apps.modules.wallets.serializer_integration import (
    assign_wallet_for_bank_movement,
    assign_wallet_for_cash_movement,
    assign_wallet_for_corporate_movement,
)
from apps.tenants.models import TenantModuleConfig


def _create_module_key_for_payment_type(payment_type: str) -> str | None:
    if payment_type == Request.PAYMENT_TYPE_CASH:
        return "cash"
    if payment_type in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        return "bank"
    if payment_type == Request.PAYMENT_TYPE_CARD:
        return "corporate_card"
    return None


def _is_module_enabled(*, tenant, module_key: str | None) -> bool:
    if not module_key:
        return False
    return TenantModuleConfig.objects.filter(
        tenant=tenant,
        module_key=module_key,
        is_enabled=True,
    ).exists()


def _already_linked(request_obj: Request) -> bool:
    ref_id = request_obj.expense_ref_id
    target = request_obj.expense_ref_target
    if not ref_id or not target:
        return False
    if target == Request.EXPENSE_REF_TARGET_CASH:
        return CashExpense.objects.filter(tenant=request_obj.tenant, id=ref_id).exists()
    if target == Request.EXPENSE_REF_TARGET_BANK:
        return BankExpense.objects.filter(tenant=request_obj.tenant, id=ref_id).exists()
    if target == Request.EXPENSE_REF_TARGET_CARD:
        return CardExpense.objects.filter(tenant=request_obj.tenant, id=ref_id).exists()
    if target == Request.EXPENSE_REF_TARGET_PAYROLL:
        return PayrollDocument.objects.filter(tenant=request_obj.tenant, id=ref_id).exists()
    return False


def create_expense_for_request_payment(*, request_obj: Request, actor_user):
    if _already_linked(request_obj):
        return request_obj.expense_ref_target, request_obj.expense_ref_id

    module_key = _create_module_key_for_payment_type(request_obj.payment_type)
    if not _is_module_enabled(tenant=request_obj.tenant, module_key=module_key):
        raise ValidationError(
            {
                "detail": (
                    f"Create payment action is unavailable: module '{module_key}' is disabled "
                    "for this tenant."
                )
            }
        )

    now_dt = timezone.now()
    created_id = None
    created_target = None

    if request_obj.payment_type == Request.PAYMENT_TYPE_CASH:
        attrs = {
            "currency": request_obj.currency,
            "wallet": None,
        }
        attrs = assign_wallet_for_cash_movement(
            instance=None,
            tenant=request_obj.tenant,
            attrs=attrs,
        )
        expense = CashExpense.objects.create(
            tenant=request_obj.tenant,
            external_id=f"req-{request_obj.id}",
            confirmed=True,
            title=request_obj.title or "",
            amount=request_obj.amount,
            currency=request_obj.currency or Request.CURRENCY_UZS,
            expense_at=now_dt,
            expense_year=request_obj.expense_year or now_dt.year,
            expense_month=request_obj.expense_month or now_dt.month,
            expense_day=request_obj.expense_day or now_dt.day,
            note=request_obj.description or "",
            payload={"request_id": request_obj.id, "source": "request_payment_create"},
            vendor=request_obj.vendor_ref,
            created_by=actor_user,
            wallet=attrs["wallet"],
        )
        created_target = Request.EXPENSE_REF_TARGET_CASH
        created_id = expense.id
    elif request_obj.payment_type in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        attrs = {"wallet": None}
        attrs = assign_wallet_for_bank_movement(
            instance=None,
            tenant=request_obj.tenant,
            attrs=attrs,
        )
        doc_date = request_obj.billing_date or timezone.localdate()
        expense = BankExpense.objects.create(
            tenant=request_obj.tenant,
            created_by=actor_user,
            row_no=0,
            doc_date=doc_date,
            process_date=doc_date,
            expense_year=request_obj.expense_year or doc_date.year,
            expense_month=request_obj.expense_month or doc_date.month,
            expense_day=request_obj.expense_day or doc_date.day,
            doc_no=f"REQ-{request_obj.id}",
            debit_turnover=request_obj.amount,
            payment_purpose=request_obj.payment_purpose or request_obj.description or request_obj.title or "-",
            vendor=request_obj.vendor_ref,
            wallet=attrs["wallet"],
        )
        created_target = Request.EXPENSE_REF_TARGET_BANK
        created_id = expense.id
    elif request_obj.payment_type == Request.PAYMENT_TYPE_CARD:
        attrs = {
            "currency": request_obj.currency,
            "wallet": None,
        }
        attrs = assign_wallet_for_corporate_movement(
            instance=None,
            tenant=request_obj.tenant,
            attrs=attrs,
        )
        expense = CardExpense.objects.create(
            tenant=request_obj.tenant,
            title=request_obj.title or "",
            amount=request_obj.amount,
            currency=request_obj.currency or Request.CURRENCY_UZS,
            expense_at=now_dt,
            note=request_obj.description or "",
            payload={"request_id": request_obj.id, "source": "request_payment_create"},
            created_by=actor_user,
            wallet=attrs["wallet"],
        )
        created_target = Request.EXPENSE_REF_TARGET_CARD
        created_id = expense.id
    else:
        raise ValidationError({"payment_type": "Unsupported payment type for create mode."})

    request_obj.expense_id = str(created_id)
    request_obj.expense_ref_id = created_id
    request_obj.expense_ref_target = created_target
    request_obj.save(update_fields=["expense_id", "expense_ref_id", "expense_ref_target"])
    return created_target, created_id


def list_payment_purposes_by_payment_type(*, tenant_id: int) -> dict[str, list[str]]:
    """Distinct payment purpose names per payment_type (form config + request history)."""

    result: dict[str, list[str]] = {pt: [] for pt, _ in Request.PAYMENT_TYPE_CHOICES}
    seen: dict[str, set[str]] = {pt: set() for pt in result}

    def _append(pt: str, name: str) -> None:
        if pt not in result:
            return
        if name not in seen[pt]:
            seen[pt].add(name)
            result[pt].append(name)

    for pt, name in (
        RequestPaymentPurposeConfig.objects.filter(
            payment_type_config__config__tenant_id=tenant_id,
            is_active=True,
        )
        .values_list("payment_type_config__payment_type", "name")
        .order_by("name", "id")
    ):
        name_s = str(name).strip()
        if name_s:
            _append(str(pt).strip(), name_s)

    for row in (
        Request.objects.filter(tenant_id=tenant_id)
        .exclude(payment_purpose="")
        .values("payment_type", "payment_purpose")
        .distinct()
        .order_by("payment_type", "payment_purpose")
    ):
        name_s = str(row["payment_purpose"]).strip()
        if name_s:
            _append(str(row["payment_type"]).strip(), name_s)

    return result
