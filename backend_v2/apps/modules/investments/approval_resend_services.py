"""Переотправка Telegram-карточек согласования вложений и выплат.

Повторяет поведение `telegram_approvals.services.resend_approval_card` для заявок на
расходы: старая карточка деактивируется, отправляется новая; строка TelegramMessage
остаётся той же, меняется только message_id, растёт resend_count.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

from apps.modules.investments import approval_services as return_services
from apps.modules.investments import project_investment_approval_services as project_services
from apps.modules.investments.models import (
    InvestmentApprovalConfigStep,
    InvestmentProjectApprovalConfigStep,
    InvestmentReturnApproval,
    ProjectInvestmentApproval,
)
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.modules.telegram_approvals.services import (
    RESEND_COOLDOWN_SECONDS,
    RESEND_MAX,
    TelegramDispatcher,
)

_NOTIFICATION_STEP_TYPES = {
    InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION,
    InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION,
}


@dataclass(frozen=True)
class _CardFlow:
    """How one approval kind builds its card (text, buttons) and names its parent record."""

    model: type
    parent_attr: str
    flow_flags: Callable
    flow_flags_kwarg: str
    is_readonly: Callable
    build_text: Callable
    build_text_kwarg: str
    build_buttons: Callable


_PROJECT_FLOW = _CardFlow(
    model=ProjectInvestmentApproval,
    parent_attr="project_investment",
    flow_flags=project_services._project_investment_flow_flags,
    flow_flags_kwarg="project_investment",
    is_readonly=project_services._project_investment_telegram_card_should_be_readonly,
    build_text=project_services.build_project_investment_approval_telegram_message,
    build_text_kwarg="project_investment",
    build_buttons=project_services._build_buttons,
)

_RETURN_FLOW = _CardFlow(
    model=InvestmentReturnApproval,
    parent_attr="invest_return",
    flow_flags=return_services._investment_flow_flags,
    flow_flags_kwarg="invest_return",
    is_readonly=return_services._investment_telegram_card_should_be_readonly,
    build_text=return_services.build_investment_return_approval_telegram_message,
    build_text_kwarg="invest_return",
    build_buttons=return_services._build_buttons,
)


def approval_can_resend(approval) -> bool:
    """Same rule as requests: pending, card already sent, resend limit not reached."""
    if approval.decision != approval.DECISION_PENDING:
        return False
    if approval.step_type in _NOTIFICATION_STEP_TYPES:
        return False
    tm = approval.telegram_message if approval.telegram_message_id else None
    if tm is None:
        return False
    return tm.resend_count < RESEND_MAX


def approval_resend_available_at(approval):
    tm = approval.telegram_message if approval.telegram_message_id else None
    if tm is None or tm.last_resend_at is None:
        return None
    available = tm.last_resend_at + datetime.timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    if available <= timezone.now():
        return None
    return available


def _resend(*, flow: _CardFlow, tenant, approval_pk: int, actor_user) -> TelegramMessage | None:
    approval = (
        flow.model.objects.select_for_update(of=("self",))
        .select_related("telegram_message", "tenant", flow.parent_attr, "approver_user")
        .filter(pk=approval_pk, tenant=tenant)
        .first()
    )
    if approval is None:
        raise ValidationError({"approval_id": "Согласование не найдено."})

    if approval.decision != approval.DECISION_PENDING:
        raise ValidationError({"detail": "Согласование уже завершено."})
    if approval.step_type in _NOTIFICATION_STEP_TYPES:
        raise ValidationError({"detail": "Уведомления не переотправляются."})

    tm = approval.telegram_message
    if tm is None:
        raise ValidationError({"detail": "Telegram-сообщение ещё не было отправлено для этого согласования."})
    if tm.resend_count >= RESEND_MAX:
        raise ValidationError({"detail": f"Достигнут лимит переотправок ({RESEND_MAX})."})

    now = timezone.now()
    if tm.last_resend_at is not None:
        elapsed = (now - tm.last_resend_at).total_seconds()
        if elapsed < RESEND_COOLDOWN_SECONDS:
            raise Throttled(wait=int(RESEND_COOLDOWN_SECONDS - elapsed) + 1)

    parent = getattr(approval, flow.parent_attr)
    blocked, current_step = flow.flow_flags(**{flow.flow_flags_kwarg: parent})
    readonly = flow.is_readonly(
        approval=approval,
        blocked_by_rejection=blocked,
        current_pending_step=current_step,
    )
    text = flow.build_text(
        **{flow.build_text_kwarg: parent},
        approval=approval,
        blocked_by_rejection=blocked,
        current_pending_step=current_step,
    )
    settings_obj = get_requests_messaging_gateway_settings(tenant=approval.tenant)
    # None on gateway failure: the caller raises outside this transaction so the
    # resend_old/resend_new history rows written by the dispatcher stay committed.
    return TelegramDispatcher(approval.tenant).resend(
        tm,
        action_deactivate=settings_obj.edit_action,
        action_send=settings_obj.send_action,
        text=text,
        buttons=[] if readonly else flow.build_buttons(approval=approval),
        approval_id=approval.id,
        request_id=getattr(approval, f"{flow.parent_attr}_id"),
        actor_user=actor_user,
    )


@transaction.atomic
def resend_project_investment_approval_card(*, tenant, approval_pk: int, actor_user) -> TelegramMessage | None:
    return _resend(flow=_PROJECT_FLOW, tenant=tenant, approval_pk=approval_pk, actor_user=actor_user)


@transaction.atomic
def resend_invest_return_approval_card(*, tenant, approval_pk: int, actor_user) -> TelegramMessage | None:
    return _resend(flow=_RETURN_FLOW, tenant=tenant, approval_pk=approval_pk, actor_user=actor_user)
