from apps.modules.payroll.constants import PORTAL_PAYOUT_BLOCK_REASON
from apps.modules.payroll.models import PayrollDocument
from apps.modules.payroll.services import add_system_comment
from apps.modules.requests.models import Request


def document_for_request(request_obj: Request) -> PayrollDocument | None:
    if (
        request_obj.payment_type != Request.PAYMENT_TYPE_PAYROLL
        or request_obj.expense_ref_target != Request.EXPENSE_REF_TARGET_PAYROLL
        or not request_obj.expense_ref_id
    ):
        return None
    return PayrollDocument.objects.filter(tenant_id=request_obj.tenant_id, pk=request_obj.expense_ref_id).first()


def suppress_payment_step_for_portal_payouts(*, request_obj: Request) -> str | None:
    document = document_for_request(request_obj)
    if document is not None and document.payout_mode == PayrollDocument.PAYOUT_MODE_PORTAL:
        return PORTAL_PAYOUT_BLOCK_REASON
    return None


def revert_document_to_draft_on_reject(*, request_obj: Request) -> None:
    document = document_for_request(request_obj)
    if document is None or document.source != PayrollDocument.SOURCE_PORTAL:
        return
    updated = PayrollDocument.objects.filter(
        pk=document.pk, status=PayrollDocument.STATUS_ACCEPTED
    ).update(status=PayrollDocument.STATUS_DRAFT)
    if updated:
        add_system_comment(
            request_obj,
            f"Начисление ЗП №{document.pk} возвращено в черновик после отклонения заявки.",
        )
