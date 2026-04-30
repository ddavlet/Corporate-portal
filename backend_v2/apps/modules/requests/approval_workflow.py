from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.modules.requests.approval_config_resolver import resolve_effective_payment_step_config_for_request
from apps.modules.requests.models import Approval, Request, RequestApprovalStepConfig
from apps.modules.requests.services import create_expense_for_request_payment

# Set on remaining pending rows when another step already rejected the request.
_STOPPED_BY_OTHER_STEP_COMMENT = "Автоматически: заявка отклонена на другом этапе."


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


def _progress_step_from_status(status: str) -> int | None:
    mapping = {
        Request.STATUS_PROGRESS_1: 1,
        Request.STATUS_PROGRESS_2: 2,
        Request.STATUS_PROGRESS_3: 3,
        Request.STATUS_PROGRESS_4: 4,
        Request.STATUS_PROGRESS_5: 5,
    }
    return mapping.get(status)


def find_approvals(
    *,
    request_obj: Request,
    step: int | None = None,
    message_sent: bool | None = None,
    decision: str | None = None,
    step_type: str | None = None,
):
    qs = Approval.objects.filter(request=request_obj)
    if step is not None:
        qs = qs.filter(step=step)
    if message_sent is not None:
        qs = qs.filter(message_sent=message_sent)
    if decision is not None:
        qs = qs.filter(decision=decision)
    if step_type is not None:
        qs = qs.filter(step_type=step_type)
    return qs


def min_pending_approval_step(*, request_id: int) -> int | None:
    """
    Smallest `step` among pending approvals for the request.

    All approval rows are created up front; only rows at this step may be acted on
    until earlier steps are fully resolved (matches Request.status / workflow).
    """
    steps = list(
        Approval.objects.filter(
            request_id=request_id,
            decision=Approval.DECISION_PENDING,
        ).values_list("step", flat=True)
    )
    return min(steps) if steps else None


def _recalculate_request_status(request_obj: Request) -> str:
    """
    Derive Request.status from Approval rows.

    If any step is rejected, the request becomes REJECTED and every remaining pending
    approval is closed so nothing is routed further (Telegram / resend / next step).
    """
    approvals_qs = Approval.objects.filter(request=request_obj)
    if not approvals_qs.exists():
        return request_obj.status

    if approvals_qs.filter(decision=Approval.DECISION_REJECTED).exists():
        next_status = Request.STATUS_REJECTED
        # Close out every still-pending row so nothing (Telegram, resend, n8n) can treat
        # downstream steps as active. Also avoids stale FK caches on approval.request.status.
        Approval.objects.filter(request=request_obj, decision=Approval.DECISION_PENDING).update(
            decision=Approval.DECISION_CANCELED,
            decided_at=timezone.now(),
            comment=_STOPPED_BY_OTHER_STEP_COMMENT,
        )
    else:
        pending_steps = list(
            approvals_qs.filter(decision=Approval.DECISION_PENDING).values_list("step", flat=True)
        )
        if pending_steps:
            pending_qs = approvals_qs.filter(decision=Approval.DECISION_PENDING)
            only_payment_pending = pending_qs.exists() and not pending_qs.exclude(
                step_type=Approval.STEP_TYPE_PAYMENT
            ).exists()
            if only_payment_pending:
                next_status = Request.STATUS_APPROVED
            else:
                next_status = _status_for_progress_step(min(pending_steps)) or request_obj.status
        else:
            has_payment_steps = approvals_qs.filter(step_type=Approval.STEP_TYPE_PAYMENT).exists()
            next_status = Request.STATUS_PAYED if has_payment_steps else Request.STATUS_APPROVED

    if request_obj.status != next_status:
        request_obj.status = next_status
        request_obj.save(update_fields=["status"])
    return request_obj.status


def route_request_approvals(*, request_obj: Request) -> None:
    """
    Status-driven orchestration:
    - work only on approvals for current request.status step,
    - send only pending + unsent rows for that step,
    - move status forward when the current step has no pending rows.
    """
    from apps.modules.telegram_approvals.services import dispatch_pending_approvals, refresh_request_messages

    with transaction.atomic():
        locked = Request.objects.select_for_update().get(pk=request_obj.pk)
        refresh_request_messages(request_obj=locked)

        while True:
            locked.refresh_from_db()
            if locked.status in {Request.STATUS_REJECTED, Request.STATUS_PAYED}:
                return

            if locked.status == Request.STATUS_APPROVED:
                dispatch_pending_approvals(
                    request_obj=locked,
                    step_type=Approval.STEP_TYPE_PAYMENT,
                )
                return

            current_step = _progress_step_from_status(locked.status)
            if current_step is None:
                return

            has_pending_on_step = find_approvals(
                request_obj=locked,
                step=current_step,
                decision=Approval.DECISION_PENDING,
            ).exists()
            if has_pending_on_step:
                dispatch_pending_approvals(request_obj=locked, step=current_step)
                return

            next_status = _status_for_progress_step(current_step + 1) or Request.STATUS_APPROVED
            if locked.status == next_status:
                return
            locked.status = next_status
            locked.save(update_fields=["status"])


def _approval_match_queryset(
    *,
    approval_id: int,
    approver_user_id: int | None,
    approver_recipient_id: int | None,
    approver_external_user_id: int | None,
    require_pending: bool,
):
    qs = Approval.objects.filter(id=approval_id)
    if require_pending:
        qs = qs.filter(decision=Approval.DECISION_PENDING)
    if approver_user_id is not None:
        qs = qs.filter(approver_user_id=approver_user_id)
    if approver_recipient_id is not None:
        qs = qs.filter(approver_recipient_id=approver_recipient_id)
    if approver_external_user_id is not None:
        qs = qs.filter(approver_user_id=approver_external_user_id)
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
        Approval.objects.filter(request__tenant=tenant, gateway_message_id=message_id)
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
    approver_recipient_id: int | None = None,
    approver_external_user_id: int | None = None,
    decision: str = Approval.DECISION_APPROVED,
    comment: str | None = None,
    decided_at=None,
) -> dict:
    if approver_user_id is None and approver_recipient_id is None and approver_external_user_id is None:
        raise ValidationError({"detail": "Approver identity is required."})
    if decision not in {Approval.DECISION_APPROVED, Approval.DECISION_REJECTED}:
        raise ValidationError({"decision": "Unsupported decision value."})

    with transaction.atomic():
        approval = _approval_match_queryset(
            approval_id=approval_id,
            approver_user_id=approver_user_id,
            approver_recipient_id=approver_recipient_id,
            approver_external_user_id=approver_external_user_id,
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

        active_step = min_pending_approval_step(request_id=request_obj.id)
        if active_step is None or approval.step != active_step:
            raise ValidationError(
                {"detail": "Этот этап согласования ещё не активен. Сначала завершите предыдущие шаги."}
            )

        if (
            decision == Approval.DECISION_APPROVED
            and approval.step_type == Approval.STEP_TYPE_PAYMENT
        ):
            step_cfg = resolve_effective_payment_step_config_for_request(
                request_obj=request_obj,
                step=approval.step,
                step_type=approval.step_type,
            )
            mode = (
                step_cfg.payment_action_mode
                if step_cfg
                else RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK
            )
            if mode == RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE:
                actor_user = approval.approver_user
                if actor_user is None:
                    raise ValidationError({"detail": "Approver user is required for create mode."})
                create_expense_for_request_payment(
                    request_obj=request_obj,
                    actor_user=actor_user,
                )

        approval.decision = decision
        approval.comment = comment
        approval.decided_at = decided_at or timezone.now()
        approval.save(update_fields=["decision", "comment", "decided_at"])

        _recalculate_request_status(request_obj)
        request_obj.refresh_from_db()
        route_request_approvals(request_obj=request_obj)
        return get_approval_full_context(request_obj=request_obj, trigger_approval=approval)
