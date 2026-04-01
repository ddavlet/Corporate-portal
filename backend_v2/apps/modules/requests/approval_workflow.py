from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.modules.requests.models import Approval, Request


class ApprovalDecisionAlreadyMade(APIException):
    status_code = 409
    default_detail = "Решение по согласованию уже принято."
    default_code = "approval_decision_already_made"


def _status_for_progress_step(step: int) -> str | None:
    mapping = {
        1: Request.STATUS_PROGRESS_1,
        2: Request.STATUS_PROGRESS_2,
        3: Request.STATUS_PROGRESS_3,
        4: Request.STATUS_PROGRESS_4,
        5: Request.STATUS_PROGRESS_5,
    }
    return mapping.get(step)


def _recalculate_request_status(request_obj: Request) -> str:
    approvals_qs = Approval.objects.filter(request=request_obj)
    if not approvals_qs.exists():
        return request_obj.status

    if approvals_qs.filter(decision=Approval.DECISION_REJECTED).exists():
        next_status = Request.STATUS_REJECTED
    else:
        pending_steps = list(
            approvals_qs.filter(decision=Approval.DECISION_PENDING).values_list("step", flat=True)
        )
        if pending_steps:
            next_status = _status_for_progress_step(min(pending_steps)) or request_obj.status
        else:
            has_payment_steps = approvals_qs.filter(step_type=Approval.STEP_TYPE_PAYMENT).exists()
            next_status = Request.STATUS_PAYED if has_payment_steps else Request.STATUS_APPROVED

    if request_obj.status != next_status:
        request_obj.status = next_status
        request_obj.save(update_fields=["status"])
    return request_obj.status


def _approval_match_queryset(
    *,
    approval_id: int,
    approver_user_id: int | None,
    approver_tg_id: int | None,
    approver_tg_from_id: int | None,
    require_pending: bool,
):
    qs = Approval.objects.filter(id=approval_id)
    if require_pending:
        qs = qs.filter(decision=Approval.DECISION_PENDING)
    if approver_user_id is not None:
        qs = qs.filter(approver_user_id=approver_user_id)
    if approver_tg_id is not None:
        qs = qs.filter(approver_tg_id=approver_tg_id)
    if approver_tg_from_id is not None:
        qs = qs.filter(approver_tg_from_id=approver_tg_from_id)
    return qs.select_related("approver_user")


def get_approval_full_context(*, request_obj: Request, trigger_approval: Approval | None = None) -> dict:
    approvals = list(
        Approval.objects.filter(request=request_obj).select_related("approver_user").order_by("step", "id")
    )
    if trigger_approval is None and approvals:
        trigger_approval = approvals[0]
    return {
        "request": request_obj,
        "trigger_approval": trigger_approval,
        "approvals": approvals,
    }


def lookup_approval_by_message_id(*, tenant, message_id: int) -> dict:
    approval = (
        Approval.objects.filter(request__tenant=tenant, message_id=message_id)
        .select_related("approver_user", "request", "request__requester")
        .first()
    )
    if approval is None:
        raise NotFound("Approval with this message_id was not found.")
    return get_approval_full_context(request_obj=approval.request, trigger_approval=approval)


def confirm_approval_by_id(
    *,
    tenant,
    approval_id: int,
    request_id: int | None = None,
    approver_user_id: int | None = None,
    approver_tg_id: int | None = None,
    approver_tg_from_id: int | None = None,
    decision: str = Approval.DECISION_APPROVED,
    comment: str | None = None,
    decided_at=None,
) -> dict:
    if approver_user_id is None and approver_tg_id is None and approver_tg_from_id is None:
        raise ValidationError({"detail": "Approver identity is required."})
    if decision not in {Approval.DECISION_PENDING, Approval.DECISION_APPROVED, Approval.DECISION_REJECTED}:
        raise ValidationError({"decision": "Unsupported decision value."})

    with transaction.atomic():
        approval = _approval_match_queryset(
            approval_id=approval_id,
            approver_user_id=approver_user_id,
            approver_tg_id=approver_tg_id,
            approver_tg_from_id=approver_tg_from_id,
            require_pending=False,
        ).select_related("request", "approver_user").first()

        if approval is None:
            if Approval.objects.filter(id=approval_id, request__tenant=tenant).exists():
                raise PermissionDenied("Approver is not assigned to this approval.")
            raise NotFound("Approval not found.")
        if approval.decision != Approval.DECISION_PENDING:
            raise ApprovalDecisionAlreadyMade()

        request_obj = Request.objects.select_for_update().filter(id=approval.request_id, tenant=tenant).first()
        if request_obj is None:
            raise NotFound("Request not found.")
        if request_id is not None and request_obj.id != request_id:
            raise ValidationError({"approval_id": "Approval does not belong to this request."})

        approval.decision = decision
        approval.comment = comment
        approval.decided_at = decided_at or timezone.now()
        approval.save(update_fields=["decision", "comment", "decided_at"])

        _recalculate_request_status(request_obj)
        # Keep Telegram cards in sync and deliver next step approvals.
        from apps.modules.telegram_approvals.services import dispatch_pending_approvals, refresh_request_messages

        refresh_request_messages(request_obj=request_obj)
        dispatch_pending_approvals(request_obj=request_obj)
        return get_approval_full_context(request_obj=request_obj, trigger_approval=approval)
