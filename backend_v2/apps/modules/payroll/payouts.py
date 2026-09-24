import datetime as dt
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.cashier.models import CashExpense
from apps.modules.payroll.constants import KIND_LABELS
from apps.modules.payroll.models import PayrollDocument, PayrollLine, PayrollPayout
from apps.modules.payroll.services import add_system_comment, current_request_for_document
from apps.modules.requests.approval_workflow import complete_request_payment_by_system
from apps.modules.requests.models import Request
from apps.modules.wallets.resolution import resolve_wallet_for_cash
from apps.tenants.models import TenantModuleConfig

ZERO = Decimal("0.00")
_STATUS_REASONS = {
    PayrollDocument.STATUS_DRAFT: "Начисление ещё не принято.",
    PayrollDocument.STATUS_CLOSED: "Начисление закрыто.",
    PayrollDocument.STATUS_CANCELLED: "Начисление отменено.",
}


def document_label(document: PayrollDocument) -> str:
    return document.doc_id or f"№{document.pk}"


def _cash_enabled(tenant) -> bool:
    return TenantModuleConfig.objects.filter(tenant=tenant, module_key="cash", is_enabled=True).exists()


def _employee_rows(document: PayrollDocument) -> list[dict]:
    accrued = (
        PayrollLine.objects.filter(document=document, employee_fk__isnull=False)
        .values("employee_fk_id", "employee_fk__full_name")
        .annotate(total=Sum("sum"))
    )
    paid = dict(
        PayrollPayout.objects.filter(document=document)
        .values("employee_id")
        .annotate(total=Sum("amount"))
        .values_list("employee_id", "total")
    )
    rows = []
    for row in accrued:
        eid = row["employee_fk_id"]
        accrued_sum = row["total"] or ZERO
        paid_sum = paid.get(eid) or ZERO
        rows.append(
            {
                "employee_id": eid,
                "full_name": row["employee_fk__full_name"],
                "accrued": accrued_sum,
                "paid": paid_sum,
                "remaining": max(accrued_sum - paid_sum, ZERO),
            }
        )
    rows.sort(key=lambda r: r["full_name"])
    return rows


def _expense_rows(document: PayrollDocument) -> list[dict]:
    expense_ids = PayrollPayout.objects.filter(document=document).values("cash_expense_id")
    return [
        {
            "cash_expense_id": exp.id,
            "date": timezone.localtime(exp.expense_at).date(),
            "amount": exp.amount,
            "wallet_id": exp.wallet_id,
        }
        for exp in CashExpense.objects.filter(pk__in=expense_ids).order_by("expense_at", "id")
    ]


def _blocked_reason(document, request_obj, rows) -> str | None:
    if document.payout_mode != PayrollDocument.PAYOUT_MODE_PORTAL:
        return "Выплаты по этому начислению ведутся вне портала."
    if document.status != PayrollDocument.STATUS_ACCEPTED:
        return _STATUS_REASONS.get(document.status, "Начисление недоступно для выплат.")
    if request_obj is None:
        return "Заявка по начислению не найдена."
    if request_obj.status != Request.STATUS_APPROVED:
        return f"Заявка не согласована (статус {request_obj.status})."
    if PayrollLine.objects.filter(document=document, employee_fk__isnull=True).exists():
        return "В начислении есть строки без сотрудника из справочника."
    if not _cash_enabled(document.tenant):
        return "Модуль «Касса» выключен."
    if sum((r["remaining"] for r in rows), ZERO) <= ZERO:
        return "Всё начисленное уже выплачено."
    return None


def payout_state(document: PayrollDocument) -> dict:
    request_obj = current_request_for_document(document)
    rows = _employee_rows(document)
    reason = _blocked_reason(document, request_obj, rows)
    accrued_total = document.lines.aggregate(s=Sum("sum"))["s"] or ZERO
    paid_total = PayrollPayout.objects.filter(document=document).aggregate(s=Sum("amount"))["s"] or ZERO
    return {
        "can_pay": reason is None,
        "reason": reason,
        "employees": rows,
        "accrued_total": accrued_total,
        "paid_total": paid_total,
        "remaining_total": max(accrued_total - paid_total, ZERO),
        "expenses": _expense_rows(document),
        "request": {"id": request_obj.id, "status": request_obj.status} if request_obj else None,
    }


def _expense_title(document: PayrollDocument) -> str:
    if document.kind and document.period_month:
        return f"ЗП: {KIND_LABELS[document.kind]} за {document.period_month:%m.%Y}"
    return f"ЗП по начислению {document_label(document)}"


def _close(document: PayrollDocument, *, request_obj: Request, actor, underpaid_comment: str | None) -> None:
    if underpaid_comment is None:
        comment = f"Выплачено полностью по начислению ЗП {document_label(document)}."
    else:
        comment = f"Закрыто с недоплатой по начислению ЗП {document_label(document)}: {underpaid_comment}"
    complete_request_payment_by_system(request_obj=request_obj, comment=comment)
    add_system_comment(request_obj, comment)
    document.status = PayrollDocument.STATUS_CLOSED
    update_fields = ["status"]
    if underpaid_comment is not None:
        document.closed_underpaid_at = timezone.now()
        document.closed_by = actor
        document.close_comment = underpaid_comment
        update_fields += ["closed_underpaid_at", "closed_by", "close_comment"]
    document.save(update_fields=update_fields)


def create_payout_expense(*, document, wallet_id: int, date: dt.date, items: list[dict], actor) -> CashExpense:
    with transaction.atomic():
        locked = PayrollDocument.objects.select_for_update().select_related("tenant").get(pk=document.pk)
        state = payout_state(locked)
        if not state["can_pay"]:
            raise ValidationError({"detail": state["reason"]})
        if not items:
            raise ValidationError({"items": "Нужен хотя бы один сотрудник."})
        rows = {r["employee_id"]: r for r in state["employees"]}
        seen: set[int] = set()
        total = ZERO
        for item in items:
            eid = item["employee_id"]
            amount = Decimal(item["amount"])
            if eid in seen:
                raise ValidationError({"items": "Сотрудник указан дважды."})
            seen.add(eid)
            row = rows.get(eid)
            if row is None:
                raise ValidationError({"items": f"Сотрудника id={eid} нет в начислении."})
            if amount <= ZERO:
                raise ValidationError({"items": f"{row['full_name']}: сумма должна быть больше нуля."})
            if amount > row["remaining"]:
                raise ValidationError(
                    {"items": f"{row['full_name']}: можно выплатить не более {row['remaining']}."}
                )
            total += amount

        try:
            wallet = resolve_wallet_for_cash(tenant=locked.tenant, currency=Request.CURRENCY_UZS, wallet_id=wallet_id)
        except ValueError as exc:
            raise ValidationError({"wallet_id": "Касса не найдена."}) from exc
        register = getattr(wallet, "cash_register", None)
        if register is not None and (register.currency or "").upper() != Request.CURRENCY_UZS:
            raise ValidationError({"wallet_id": "Выплата ЗП возможна только из кассы в UZS."})

        seq = PayrollPayout.objects.filter(document=locked).values("cash_expense_id").distinct().count() + 1
        expense_at = timezone.make_aware(dt.datetime.combine(date, timezone.localtime().time()))
        expense = CashExpense.objects.create(
            tenant=locked.tenant,
            external_id=f"zp-{locked.pk}-{seq}",
            confirmed=True,
            title=_expense_title(locked)[:255],
            amount=total,
            currency=Request.CURRENCY_UZS,
            expense_at=expense_at,
            expense_year=date.year,
            expense_month=date.month,
            expense_day=date.day,
            note=f"Выплата ЗП по начислению {document_label(locked)}",
            payload={"source": "payroll_payout"},
            vendor=None,
            created_by=actor,
            wallet=wallet,
        )
        for item in items:
            PayrollPayout.objects.create(
                tenant=locked.tenant,
                document=locked,
                employee_id=item["employee_id"],
                cash_expense=expense,
                amount=Decimal(item["amount"]),
                created_by=actor,
            )
        if payout_state(locked)["remaining_total"] <= ZERO:
            _close(locked, request_obj=current_request_for_document(locked), actor=actor, underpaid_comment=None)
    return expense


def close_underpaid(*, document, actor, comment: str) -> PayrollDocument:
    comment = (comment or "").strip()
    if not comment:
        raise ValidationError({"comment": "Укажите причину закрытия с недоплатой."})
    with transaction.atomic():
        locked = PayrollDocument.objects.select_for_update().select_related("tenant").get(pk=document.pk)
        request_obj = current_request_for_document(locked)
        if locked.payout_mode != PayrollDocument.PAYOUT_MODE_PORTAL or locked.status != PayrollDocument.STATUS_ACCEPTED:
            raise ValidationError({"detail": "Закрыть можно только принятое начисление с выплатами через портал."})
        if request_obj is None or request_obj.status != Request.STATUS_APPROVED:
            raise ValidationError({"detail": "Заявка должна быть согласована."})
        _close(locked, request_obj=request_obj, actor=actor, underpaid_comment=comment)
    return locked
