from __future__ import annotations

from dataclasses import dataclass
from html import escape

from django.db import transaction
from django.db.models import Min
from django.utils import timezone
from django.utils.formats import date_format

from apps.modules.investments.approval_services import INVESTMENT_APPROVAL_CASCADE_REJECTION_COMMENT
from apps.modules.investments.models import (
    InvestmentProjectApprovalConfig,
    InvestmentProjectApprovalConfigStep,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.services import (
    _display_user_name,
    _format_amount_for_telegram,
    get_tenant_bot_token,
    post_messaging_gateway,
)

_TG_CARD_SEP = "\u2500" * 17


def resolve_investment_project_approval_config(*, tenant) -> InvestmentProjectApprovalConfig | None:
    cfg = (
        InvestmentProjectApprovalConfig.objects.filter(tenant=tenant, is_enabled=True)
        .prefetch_related("steps__approver_users")
        .first()
    )
    return cfg


class InvestmentProjectApprovalDecisionAlreadyMade(Exception):
    pass


@dataclass(frozen=True)
class InvestmentProjectApprovalDecisionResult:
    approval: ProjectInvestmentApproval
    project_investment: ProjectInvestment


def _button_data(*, approval_id: int, decision: str) -> str:
    code = "a" if decision == ProjectInvestmentApproval.DECISION_APPROVED else "r"
    return f"invp_{approval_id}:{code}"


def _project_investment_flow_flags(*, project_investment: ProjectInvestment) -> tuple[bool, int | None]:
    blocked = ProjectInvestmentApproval.objects.filter(
        project_investment=project_investment,
        decision=ProjectInvestmentApproval.DECISION_REJECTED,
    ).exists()
    current_step = (
        ProjectInvestmentApproval.objects.filter(
            tenant=project_investment.tenant,
            project_investment=project_investment,
            decision=ProjectInvestmentApproval.DECISION_PENDING,
        ).aggregate(value=Min("step"))["value"]
    )
    return blocked, current_step


def _project_investment_telegram_card_should_be_readonly(
    *,
    approval: ProjectInvestmentApproval,
    blocked_by_rejection: bool,
    current_pending_step: int | None,
) -> bool:
    if approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION:
        return True
    if approval.decision != ProjectInvestmentApproval.DECISION_PENDING:
        return True
    if blocked_by_rejection:
        return True
    if current_pending_step is None:
        return True
    if approval.step != current_pending_step:
        return True
    return False


def build_project_investment_approval_telegram_message(
    *,
    project_investment: ProjectInvestment,
    approval: ProjectInvestmentApproval,
    blocked_by_rejection: bool,
    current_pending_step: int | None,
) -> str:
    """HTML body for Telegram (aligned with investment return approval cards)."""
    pi = project_investment
    company_name = pi.company.name if pi.company else pi.tenant.name
    amount_text = escape(_format_amount_for_telegram(pi.amount))
    currency_text = escape((pi.currency or "").upper() or "-")
    date_text = escape(date_format(pi.date, "j E Y", use_l10n=True)) if pi.date else "-"
    comment_raw = (pi.comment or "").strip()

    readonly = _project_investment_telegram_card_should_be_readonly(
        approval=approval,
        blocked_by_rejection=blocked_by_rejection,
        current_pending_step=current_pending_step,
    )

    if approval.decision == ProjectInvestmentApproval.DECISION_REJECTED:
        header = "❌ Заявка на вложение отклонена"
    elif blocked_by_rejection:
        header = "⛔️ Согласование остановлено"
    elif current_pending_step is None:
        header = "✅ Заявка на вложение подтверждена"
    elif approval.decision == ProjectInvestmentApproval.DECISION_APPROVED:
        header = f"✅ Шаг {approval.step} согласован"
    elif (
        approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION
        and approval.decision == ProjectInvestmentApproval.DECISION_PENDING
        and current_pending_step is not None
        and approval.step == current_pending_step
    ):
        header = f"📢 Уведомление — шаг {approval.step}"
    elif readonly:
        header = "⏳ Ожидание предыдущих шагов"
    elif approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_CONFIRMATION:
        header = f"💰 Подтверждение вложения — шаг {approval.step}"
    else:
        header = f"📋 Проверка заявки на вложение — шаг {approval.step}"

    action_hint = ""
    if not readonly and approval.decision == ProjectInvestmentApproval.DECISION_PENDING:
        if approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            action_hint = ""
        elif approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_CONFIRMATION:
            action_hint = "\n\nПодтвердите вложение средств по заявке кнопками ниже."
        else:
            action_hint = "\n\nПроверьте данные заявки на вложение и ответьте кнопками ниже."

    expected_approver_footer = ""
    if (
        not readonly
        and approval.decision == ProjectInvestmentApproval.DECISION_PENDING
        and approval.step_type != InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION
    ):
        who = _display_user_name(getattr(approval, "approver_user", None))
        if who and who != "-":
            expected_approver_footer = f"\n\n✍️ Ожидается подтверждение от: <b>{escape(who)}</b>"

    sep = _TG_CARD_SEP
    parts: list[str] = [
        f"<b>{escape(header)}</b>\n\n",
        f"<b>Заявка на вложение №{pi.id}</b>\n",
        f"{sep}\n",
        f"🏢 Компания: <b>{escape(str(company_name))}</b>\n",
        f"📅 Дата: {date_text}\n\n",
        f"{sep}\n",
        f"💵 <b>{amount_text} {currency_text}</b>\n",
    ]
    if comment_raw:
        parts.extend([f"\n{sep}\n", f"💬 Комментарий: {escape(comment_raw)}\n"])
    parts.append(f"{action_hint}{expected_approver_footer}")
    return "".join(parts)


def _build_buttons(*, approval: ProjectInvestmentApproval) -> list[list[dict]]:
    if approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION:
        return []
    if approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_CONFIRMATION:
        return [
            [
                {"label": "✅ Выплачено", "value": _button_data(approval_id=approval.id, decision="approved")},
                {"label": "❌ Отменить", "value": _button_data(approval_id=approval.id, decision="rejected")},
            ]
        ]
    return [
        [
            {"label": "✅ Проверено", "value": _button_data(approval_id=approval.id, decision="approved")},
            {"label": "❌ Есть ошибка", "value": _button_data(approval_id=approval.id, decision="rejected")},
        ]
    ]


def _project_investment_messaging_payload(
    *,
    action: str,
    approval: ProjectInvestmentApproval,
    message_text: str,
    include_buttons: bool,
) -> dict:
    payload: dict = {
        "action": action,
        "text": message_text,
        "recipient_id": str(approval.approver_recipient_id),
        "bot_token": get_tenant_bot_token(approval.tenant),
        "tenant_id": str(approval.tenant_id),
        "approval_id": str(approval.id),
        "request_id": approval.project_investment_id,
        "buttons": _build_buttons(approval=approval) if include_buttons else [],
    }
    if approval.gateway_message_id:
        payload["message_id"] = approval.gateway_message_id
    return payload


def _dispatch_approval_message(*, approval: ProjectInvestmentApproval, include_buttons: bool = True) -> bool:
    if approval.approver_recipient_id is None:
        return False
    settings_obj = get_requests_messaging_gateway_settings(tenant=approval.tenant)
    blocked, current_step = _project_investment_flow_flags(project_investment=approval.project_investment)
    message_text = build_project_investment_approval_telegram_message(
        project_investment=approval.project_investment,
        approval=approval,
        blocked_by_rejection=blocked,
        current_pending_step=current_step,
    )
    payload = _project_investment_messaging_payload(
        action=settings_obj.send_action,
        approval=approval,
        message_text=message_text,
        include_buttons=include_buttons,
    )
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
    return isinstance(message_id, int)


def refresh_project_investment_approval_messages(*, project_investment: ProjectInvestment) -> int:
    project_investment.refresh_from_db()
    blocked, current_step = _project_investment_flow_flags(project_investment=project_investment)
    approvals = list(
        ProjectInvestmentApproval.objects.filter(
            project_investment=project_investment,
            message_sent=True,
            gateway_message_id__isnull=False,
            approver_recipient_id__isnull=False,
        ).select_related("project_investment", "project_investment__company", "tenant")
    )
    updated = 0
    for approval in approvals:
        readonly = _project_investment_telegram_card_should_be_readonly(
            approval=approval,
            blocked_by_rejection=blocked,
            current_pending_step=current_step,
        )
        if _edit_project_investment_approval_message(approval=approval, include_buttons=not readonly):
            updated += 1
    return updated


def _edit_project_investment_approval_message(*, approval: ProjectInvestmentApproval, include_buttons: bool) -> bool:
    if not approval.gateway_message_id or approval.approver_recipient_id is None:
        return False
    pi = approval.project_investment
    blocked, current_step = _project_investment_flow_flags(project_investment=pi)
    message_text = build_project_investment_approval_telegram_message(
        project_investment=pi,
        approval=approval,
        blocked_by_rejection=blocked,
        current_pending_step=current_step,
    )
    settings_obj = get_requests_messaging_gateway_settings(tenant=approval.tenant)
    payload = _project_investment_messaging_payload(
        action=settings_obj.edit_action,
        approval=approval,
        message_text=message_text,
        include_buttons=include_buttons,
    )
    return post_messaging_gateway(tenant=approval.tenant, payload=payload) is not None


def deactivate_project_investment_approval_buttons(*, approval: ProjectInvestmentApproval) -> bool:
    return _edit_project_investment_approval_message(approval=approval, include_buttons=False)


def create_approvals_for_project_investment(*, project_investment: ProjectInvestment) -> int:
    config = resolve_investment_project_approval_config(tenant=project_investment.tenant)
    if not config:
        return 0

    created = 0
    for step in config.steps.filter(is_enabled=True).order_by("step", "id"):
        if step.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            approvers = list(step.approver_users.filter(is_active=True))
            record_user = approvers[0] if approvers else project_investment.created_by
            recipient_id = step.payment_chat_id
            ProjectInvestmentApproval.objects.create(
                tenant=project_investment.tenant,
                project_investment=project_investment,
                step=step.step,
                step_type=step.step_type,
                approver_user=record_user,
                approver_recipient_id=recipient_id,
                approver_external_user_id=record_user.telegram_from_id,
            )
            created += 1
            continue
        for approver in step.approver_users.filter(is_active=True):
            recipient_id = (
                step.payment_chat_id
                if step.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_CONFIRMATION
                else approver.telegram_chat_id
            )
            ProjectInvestmentApproval.objects.create(
                tenant=project_investment.tenant,
                project_investment=project_investment,
                step=step.step,
                step_type=step.step_type,
                approver_user=approver,
                approver_recipient_id=recipient_id,
                approver_external_user_id=approver.telegram_from_id,
            )
            created += 1
    return created


def dispatch_pending_project_investment_approvals(*, project_investment: ProjectInvestment) -> int:
    pending_step = (
        ProjectInvestmentApproval.objects.filter(
            tenant=project_investment.tenant,
            project_investment=project_investment,
            decision=ProjectInvestmentApproval.DECISION_PENDING,
        ).aggregate(value=Min("step"))["value"]
    )
    if pending_step is None:
        return 0
    rows = list(
        ProjectInvestmentApproval.objects.filter(
            tenant=project_investment.tenant,
            project_investment=project_investment,
            step=pending_step,
            decision=ProjectInvestmentApproval.DECISION_PENDING,
        ).select_related("project_investment", "tenant")
    )
    any_notification_finalized = False
    for row in rows:
        if row.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            ok = _dispatch_approval_message(approval=row, include_buttons=False)
            if ok:
                now = timezone.now()
                updated = ProjectInvestmentApproval.objects.filter(
                    pk=row.pk,
                    decision=ProjectInvestmentApproval.DECISION_PENDING,
                ).update(
                    decision=ProjectInvestmentApproval.DECISION_APPROVED,
                    decided_at=now,
                )
                if updated:
                    any_notification_finalized = True
        else:
            _dispatch_approval_message(approval=row, include_buttons=True)
    if any_notification_finalized:
        return route_project_investment_approvals(project_investment=project_investment)
    return len(rows)


def route_project_investment_approvals(*, project_investment: ProjectInvestment) -> int:
    refresh_project_investment_approval_messages(project_investment=project_investment)
    pending = ProjectInvestmentApproval.objects.filter(
        tenant=project_investment.tenant,
        project_investment=project_investment,
        decision=ProjectInvestmentApproval.DECISION_PENDING,
    ).exists()
    if not pending:
        has_rejected = ProjectInvestmentApproval.objects.filter(
            tenant=project_investment.tenant,
            project_investment=project_investment,
            decision=ProjectInvestmentApproval.DECISION_REJECTED,
        ).exists()
        if has_rejected:
            if project_investment.confirmed:
                project_investment.confirmed = False
                project_investment.save(update_fields=["confirmed"])
            return 0
        if not project_investment.confirmed:
            project_investment.confirmed = True
            project_investment.save(update_fields=["confirmed"])
        return 0
    return dispatch_pending_project_investment_approvals(project_investment=project_investment)


def reject_remaining_pending_project_investment_approvals(*, project_investment: ProjectInvestment) -> int:
    """После отказа: все ещё ожидающие строки по этой заявке → отказ (цепочка не идёт дальше)."""
    now = timezone.now()
    return ProjectInvestmentApproval.objects.filter(
        project_investment=project_investment,
        decision=ProjectInvestmentApproval.DECISION_PENDING,
    ).update(
        decision=ProjectInvestmentApproval.DECISION_REJECTED,
        decision_comment=INVESTMENT_APPROVAL_CASCADE_REJECTION_COMMENT,
        decided_at=now,
        updated_at=now,
    )


def confirm_project_investment_approval_by_id(
    *,
    tenant,
    approval_id: int,
    approver_recipient_id: int | None = None,
    approver_external_user_id: int | None = None,
    decision: str,
    comment: str = "",
) -> InvestmentProjectApprovalDecisionResult:
    with transaction.atomic():
        approval = (
            ProjectInvestmentApproval.objects.select_for_update()
            .select_related("project_investment", "approver_user", "tenant")
            .filter(id=approval_id, tenant=tenant)
            .first()
        )
        if approval is None:
            raise ValueError("Approval not found.")
        if approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            raise ValueError("Этап notification подтверждается автоматически после отправки сообщения.")
        if approval.decision != ProjectInvestmentApproval.DECISION_PENDING:
            raise InvestmentProjectApprovalDecisionAlreadyMade()
        if approver_recipient_id is not None and approval.approver_recipient_id not in (None, approver_recipient_id):
            raise ValueError("Chat is not allowed for this approval.")
        if approver_external_user_id is not None and approval.approver_external_user_id not in (
            None,
            approver_external_user_id,
        ):
            raise ValueError("User is not allowed for this approval.")

        current_step = (
            ProjectInvestmentApproval.objects.filter(
                tenant=tenant,
                project_investment=approval.project_investment,
                decision=ProjectInvestmentApproval.DECISION_PENDING,
            ).aggregate(value=Min("step"))["value"]
        )
        if current_step is None or approval.step != current_step:
            raise ValueError("Approval step is not active.")

        approval.decision = decision
        approval.decision_comment = comment or ""
        approval.decided_at = timezone.now()
        approval.save(update_fields=["decision", "decision_comment", "decided_at", "updated_at"])

        if decision == ProjectInvestmentApproval.DECISION_REJECTED:
            reject_remaining_pending_project_investment_approvals(project_investment=approval.project_investment)

        route_project_investment_approvals(project_investment=approval.project_investment)
        approval.project_investment.refresh_from_db()
        return InvestmentProjectApprovalDecisionResult(
            approval=approval,
            project_investment=approval.project_investment,
        )
