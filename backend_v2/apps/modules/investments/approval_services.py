from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from apps.modules.investments.models import (
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentReturnApproval,
    InvestReturn,
)
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.services import post_messaging_gateway, _get_tenant_bot_token


class InvestmentApprovalDecisionAlreadyMade(Exception):
    pass


@dataclass(frozen=True)
class InvestmentApprovalDecisionResult:
    approval: InvestmentReturnApproval
    invest_return: InvestReturn


def _button_data(*, approval_id: int, decision: str) -> str:
    code = "a" if decision == InvestmentReturnApproval.DECISION_APPROVED else "r"
    return f"inv_{approval_id}:{code}"


def _build_message(*, invest_return: InvestReturn) -> str:
    company_name = invest_return.company.name if invest_return.company else invest_return.tenant.name
    amount = invest_return.sum
    currency = (invest_return.currency or "").upper()
    return (
        f"Новая выплата по {company_name}\n\n"
        f"Сумма: {amount} {currency}\n\n"
        "Пожалуйста, подтвердите получение"
    )


def _build_buttons(*, approval: InvestmentReturnApproval) -> list[list[dict]]:
    if approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION:
        return [
            [
                {"label": "✅ Получено", "value": _button_data(approval_id=approval.id, decision="approved")},
                {"label": "❌ Отменить", "value": _button_data(approval_id=approval.id, decision="rejected")},
            ]
        ]
    return [
        [
            {"label": "✅ Проверено", "value": _button_data(approval_id=approval.id, decision="approved")},
            {"label": "❌ Есть ошибка", "value": _button_data(approval_id=approval.id, decision="rejected")},
        ]
    ]


def _dispatch_approval_message(*, approval: InvestmentReturnApproval) -> None:
    if approval.approver_recipient_id is None:
        return
    settings_obj = get_requests_messaging_gateway_settings(tenant=approval.tenant)
    payload = {
        "action": settings_obj.send_action,
        "text": _build_message(invest_return=approval.invest_return),
        "recipient_id": str(approval.approver_recipient_id),
        "bot_token": _get_tenant_bot_token(approval.tenant),
        "tenant_id": str(approval.tenant_id),
        "approval_id": str(approval.id),
        "request_id": approval.invest_return_id,
        "buttons": _build_buttons(approval=approval),
    }
    response_data = post_messaging_gateway(tenant=approval.tenant, payload=payload) or {}
    message_id = response_data.get("message_id")
    if message_id in (None, "") and isinstance(response_data.get("result"), dict):
        message_id = response_data["result"].get("message_id")
    updates = []
    if isinstance(message_id, int):
        approval.gateway_message_id = message_id
        updates.append("gateway_message_id")
    if not approval.message_sent:
        approval.message_sent = True
        updates.append("message_sent")
    if approval.message_sent_at is None:
        approval.message_sent_at = timezone.now()
        updates.append("message_sent_at")
    if updates:
        approval.save(update_fields=updates)


def create_approvals_for_invest_return(*, invest_return: InvestReturn) -> int:
    config = (
        InvestmentApprovalConfig.objects.filter(tenant=invest_return.tenant, is_enabled=True)
        .prefetch_related("steps__approver_users")
        .first()
    )
    if not config:
        return 0

    created = 0
    for step in config.steps.filter(is_enabled=True).order_by("step", "id"):
        for approver in step.approver_users.filter(is_active=True):
            recipient_id = (
                step.payment_chat_id
                if step.step_type == InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION
                else approver.telegram_chat_id
            )
            InvestmentReturnApproval.objects.create(
                tenant=invest_return.tenant,
                invest_return=invest_return,
                step=step.step,
                step_type=step.step_type,
                approver_user=approver,
                approver_recipient_id=recipient_id,
                approver_external_user_id=approver.telegram_from_id,
            )
            created += 1
    return created


def dispatch_pending_invest_return_approvals(*, invest_return: InvestReturn) -> int:
    pending_step = (
        InvestmentReturnApproval.objects.filter(
            tenant=invest_return.tenant,
            invest_return=invest_return,
            decision=InvestmentReturnApproval.DECISION_PENDING,
        ).aggregate(value=Min("step"))["value"]
    )
    if pending_step is None:
        return 0
    rows = list(
        InvestmentReturnApproval.objects.filter(
            tenant=invest_return.tenant,
            invest_return=invest_return,
            step=pending_step,
            decision=InvestmentReturnApproval.DECISION_PENDING,
        ).select_related("invest_return", "tenant")
    )
    for row in rows:
        _dispatch_approval_message(approval=row)
    return len(rows)


def route_invest_return_approvals(*, invest_return: InvestReturn) -> int:
    pending = InvestmentReturnApproval.objects.filter(
        tenant=invest_return.tenant,
        invest_return=invest_return,
        decision=InvestmentReturnApproval.DECISION_PENDING,
    ).exists()
    if not pending:
        has_rejected = InvestmentReturnApproval.objects.filter(
            tenant=invest_return.tenant,
            invest_return=invest_return,
            decision=InvestmentReturnApproval.DECISION_REJECTED,
        ).exists()
        if has_rejected:
            if invest_return.confirmed:
                invest_return.confirmed = False
                invest_return.save(update_fields=["confirmed"])
            return 0
        if not invest_return.confirmed:
            invest_return.confirmed = True
            invest_return.save(update_fields=["confirmed"])
        return 0
    return dispatch_pending_invest_return_approvals(invest_return=invest_return)


def confirm_invest_return_approval_by_id(
    *,
    tenant,
    approval_id: int,
    approver_recipient_id: int | None = None,
    approver_external_user_id: int | None = None,
    decision: str,
    comment: str = "",
) -> InvestmentApprovalDecisionResult:
    with transaction.atomic():
        approval = (
            InvestmentReturnApproval.objects.select_for_update()
            .select_related("invest_return", "approver_user", "tenant")
            .filter(id=approval_id, tenant=tenant)
            .first()
        )
        if approval is None:
            raise ValueError("Approval not found.")
        if approval.decision != InvestmentReturnApproval.DECISION_PENDING:
            raise InvestmentApprovalDecisionAlreadyMade()
        if approver_recipient_id is not None and approval.approver_recipient_id not in (None, approver_recipient_id):
            raise ValueError("Chat is not allowed for this approval.")
        if approver_external_user_id is not None and approval.approver_external_user_id not in (
            None,
            approver_external_user_id,
        ):
            raise ValueError("User is not allowed for this approval.")

        current_step = (
            InvestmentReturnApproval.objects.filter(
                tenant=tenant,
                invest_return=approval.invest_return,
                decision=InvestmentReturnApproval.DECISION_PENDING,
            ).aggregate(value=Min("step"))["value"]
        )
        if current_step is None or approval.step != current_step:
            raise ValueError("Approval step is not active.")

        approval.decision = decision
        approval.decision_comment = comment or ""
        approval.decided_at = timezone.now()
        approval.save(update_fields=["decision", "decision_comment", "decided_at", "updated_at"])

        route_invest_return_approvals(invest_return=approval.invest_return)
        approval.invest_return.refresh_from_db()
        return InvestmentApprovalDecisionResult(approval=approval, invest_return=approval.invest_return)
