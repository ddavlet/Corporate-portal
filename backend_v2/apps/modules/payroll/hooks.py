import logging

from apps.modules.payroll.constants import PORTAL_PAYOUT_BLOCK_REASON
from apps.modules.payroll.models import PayrollDocument, PayrollPayout
from apps.modules.payroll.services import add_system_comment
from apps.modules.payroll.utils import tenant_has_payroll_module_enabled
from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)


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
    if document is None or document.payout_mode != PayrollDocument.PAYOUT_MODE_PORTAL:
        return None
    # Graceful degradation: if the payroll module has been disabled for the tenant
    # (e.g. admin turned it off), stop blocking the payment step so the request falls
    # back to the normal Telegram/manual payment flow instead of getting stuck with no
    # way to pay it (payroll's own payout UI is unreachable without the module).
    if not tenant_has_payroll_module_enabled(request_obj.tenant):
        return None
    return PORTAL_PAYOUT_BLOCK_REASON


def revert_document_to_draft_on_reject(*, request_obj: Request) -> None:
    document = document_for_request(request_obj)
    if document is None or document.source != PayrollDocument.SOURCE_PORTAL:
        return
    if PayrollPayout.objects.filter(document=document).exists():
        # Should be unreachable in the normal flow (payment step is suppressed for
        # portal-mode docs — see suppress_payment_step_for_portal_payouts — and payouts
        # require STATUS_ACCEPTED), but a document with real payouts against it must
        # never be silently moved back to draft (its lines could then be edited/deleted
        # out from under the payouts). Log and no-op instead.
        logger.warning(
            "payroll: reject received for document_id=%s with existing payouts, not reverting to draft",
            document.pk,
        )
        return
    updated = PayrollDocument.objects.filter(
        pk=document.pk, status=PayrollDocument.STATUS_ACCEPTED
    ).update(status=PayrollDocument.STATUS_DRAFT)
    if updated:
        add_system_comment(
            request_obj,
            f"Начисление ЗП №{document.pk} возвращено в черновик после отклонения заявки.",
        )
