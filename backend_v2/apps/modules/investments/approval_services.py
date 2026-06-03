from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape

from django.db import transaction
from django.db.models import Min
from django.utils import timezone
from django.utils.formats import date_format

from apps.modules.investments.models import (
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentReturnApproval,
    InvestReturn,
)
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.services import (
    TelegramDispatcher,
    _display_user_name,
    _format_amount_for_telegram,
    get_tenant_bot_token,
)

INVESTMENT_APPROVAL_CASCADE_REJECTION_COMMENT = (
    "Согласование остановлено: получен отказ. Дальнейшие этапы не выполняются."
)


def resolve_investment_approval_config(
    *, tenant, payout_type: str, payout_recipient: str
) -> InvestmentApprovalConfig | None:
    """Цепочка: тип+получатель → только тип → глобально+получатель → глобальный дефолт."""
    base = InvestmentApprovalConfig.objects.filter(tenant=tenant, is_enabled=True).prefetch_related(
        "steps__approver_users"
    )
    for filt in (
        lambda q: q.filter(return_type=payout_type, recipient=payout_recipient),
        lambda q: q.filter(return_type=payout_type, recipient__isnull=True),
        lambda q: q.filter(return_type__isnull=True, recipient=payout_recipient),
        lambda q: q.filter(return_type__isnull=True, recipient__isnull=True),
    ):
        hit = filt(base).first()
        if hit:
            return hit
    return None


class InvestmentApprovalDecisionAlreadyMade(Exception):
    pass


@dataclass(frozen=True)
class InvestmentApprovalDecisionResult:
    approval: InvestmentReturnApproval
    invest_return: InvestReturn


def _button_data(*, approval_id: int, decision: str) -> str:
    code = "a" if decision == InvestmentReturnApproval.DECISION_APPROVED else "r"
    return f"inv_{approval_id}:{code}"


_TG_CARD_SEP = "\u2500" * 17


def _invest_return_step_phase_label(step_type: str) -> str:
    if step_type == InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION:
        return "подтверждение"
    if step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
        return "уведомление"
    return "проверка"


def _format_cbu_rate_uzs_per_usd(*, rate) -> str:
    try:
        q = Decimal(str(rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return _format_amount_for_telegram(rate)
    return format(q, ",.2f").replace(",", " ")


def _investment_flow_flags(*, invest_return: InvestReturn) -> tuple[bool, int | None]:
    blocked = InvestmentReturnApproval.objects.filter(
        invest_return=invest_return,
        decision=InvestmentReturnApproval.DECISION_REJECTED,
    ).exists()
    current_step = (
        InvestmentReturnApproval.objects.filter(
            tenant=invest_return.tenant,
            invest_return=invest_return,
            decision=InvestmentReturnApproval.DECISION_PENDING,
        ).aggregate(value=Min("step"))["value"]
    )
    return blocked, current_step


def _investment_telegram_card_should_be_readonly(
    *,
    approval: InvestmentReturnApproval,
    blocked_by_rejection: bool,
    current_pending_step: int | None,
) -> bool:
    if approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
        return True
    if approval.decision != InvestmentReturnApproval.DECISION_PENDING:
        return True
    if blocked_by_rejection:
        return True
    if current_pending_step is None:
        return True
    if approval.step != current_pending_step:
        return True
    return False


def build_investment_return_approval_telegram_message(
    *,
    invest_return: InvestReturn,
    approval: InvestmentReturnApproval,
    blocked_by_rejection: bool,
    current_pending_step: int | None,
) -> str:
    """HTML body for Telegram / messaging gateway (same amount style as request approvals)."""
    ir = invest_return
    company_name = ir.company.name if ir.company else ir.tenant.name
    amount_text = escape(_format_amount_for_telegram(ir.sum))
    currency_text = escape((ir.currency or "").upper() or "-")
    date_text = escape(date_format(ir.date, "j E Y", use_l10n=True)) if ir.date else "-"
    bd = getattr(ir, "billing_date", None)
    billing_month_text = (
        escape(date_format(date(bd.year, bd.month, 1), "F Y", use_l10n=True)) if bd else "-"
    )
    type_text = escape(str(ir.get_type_display()))
    recipient_text = escape(str(ir.get_recipient_display()))
    comment_raw = (ir.comment or "").strip()
    comment_line = f"💬 Комментарий: {escape(comment_raw)}\n" if comment_raw else ""
    show_fx_block = ir.sum_uzs is not None and ir.cbu_usd_uzs_rate is not None
    uzs_amount_plain = _format_amount_for_telegram(ir.sum_uzs) if show_fx_block else ""
    uzs_amount_text = escape(uzs_amount_plain)
    rate_plain = _format_cbu_rate_uzs_per_usd(rate=ir.cbu_usd_uzs_rate) if show_fx_block else ""
    rate_text = escape(rate_plain)

    readonly = _investment_telegram_card_should_be_readonly(
        approval=approval,
        blocked_by_rejection=blocked_by_rejection,
        current_pending_step=current_pending_step,
    )

    if approval.decision == InvestmentReturnApproval.DECISION_REJECTED:
        header = "❌ Выплата отклонена"
    elif blocked_by_rejection:
        header = "🚫 Согласование остановлено"
    elif current_pending_step is None:
        header = "✅ Выплата полностью подтверждена"
    elif approval.decision == InvestmentReturnApproval.DECISION_APPROVED:
        header = f"✅ Шаг {approval.step} согласован"
    elif (
        approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION
        and approval.decision == InvestmentReturnApproval.DECISION_PENDING
        and current_pending_step is not None
        and approval.step == current_pending_step
    ):
        header = f"📢 Уведомление — шаг {approval.step}"
    elif readonly:
        header = "⏳ Ожидание предыдущих шагов"
    elif approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION:
        header = f"💰 Подтверждение получения — шаг {approval.step}"
    else:
        header = f"🔍 Проверка выплаты — шаг {approval.step}"

    action_hint = ""
    if not readonly and approval.decision == InvestmentReturnApproval.DECISION_PENDING:
        if approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            action_hint = ""
        elif approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION:
            action_hint = "\n\nПодтвердите получение средств кнопками ниже."
        else:
            action_hint = "\n\nПроверьте реквизиты и сумму, затем ответьте кнопками ниже."

    expected_approver_footer = ""
    if (
        not readonly
        and approval.decision == InvestmentReturnApproval.DECISION_PENDING
        and approval.step_type != InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION
    ):
        who = _display_user_name(getattr(approval, "approver_user", None))
        if who and who != "-":
            expected_approver_footer = f"\n\n✍️ Ожидается подтверждение от: <b>{escape(who)}</b>"

    phase = _invest_return_step_phase_label(approval.step_type)
    sep = _TG_CARD_SEP
    parts: list[str] = [
        f"<b>{escape(header)}</b>\n\n",
        f"💰 <b>Выплата №{ir.id} — {escape(phase)}</b>\n",
        f"{sep}\n",
        f"🏢 Компания: <b>{escape(str(company_name))}</b>\n",
        f"👤 Получатель: {recipient_text}\n",
        f"📅 Месяц: {billing_month_text} · {date_text}\n",
        f"{sep}\n",
    ]
    if show_fx_block:
        parts.extend(
            [
                f"💵 <b>{amount_text} {currency_text}</b>\n",
                f"🇺🇿 {uzs_amount_text} UZS\n",
                f"📊 Курс CBU: {rate_text} UZS/$\n",
                f"{sep}\n",
            ]
        )
    else:
        parts.append(f"💵 <b>{amount_text} {currency_text}</b>\n{sep}\n")
    parts.extend(
        [
            f"🏷 Тип: {type_text}\n",
            f"{comment_line}",
            f"{action_hint}",
            f"{expected_approver_footer}",
        ]
    )
    return "".join(parts)


def _build_buttons(*, approval: InvestmentReturnApproval) -> list[list[dict]]:
    if approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
        return []
    if approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION:
        return [
            [
                {"label": "✅ Подтвердить", "value": _button_data(approval_id=approval.id, decision="approved")},
                {"label": "❌ Отклонить", "value": _button_data(approval_id=approval.id, decision="rejected")},
            ]
        ]
    return [
        [
            {"label": "✅ Проверено", "value": _button_data(approval_id=approval.id, decision="approved")},
            {"label": "❌ Есть ошибка", "value": _button_data(approval_id=approval.id, decision="rejected")},
        ]
    ]


def _dispatch_approval_message(*, approval: InvestmentReturnApproval, include_buttons: bool = True) -> bool:
    if approval.approver_recipient_id is None:
        return False
    dispatcher = TelegramDispatcher(approval.tenant)
    settings_obj = get_requests_messaging_gateway_settings(tenant=approval.tenant)
    blocked, current_step = _investment_flow_flags(invest_return=approval.invest_return)
    message_text = build_investment_return_approval_telegram_message(
        invest_return=approval.invest_return,
        approval=approval,
        blocked_by_rejection=blocked,
        current_pending_step=current_step,
    )
    message = dispatcher.send(
        action=settings_obj.send_action,
        recipient_id=approval.approver_recipient_id,
        text=message_text,
        buttons=_build_buttons(approval=approval) if include_buttons else [],
        link=approval,
        external_user_id=approval.approver_external_user_id,
        approval_id=approval.id,
        request_id=approval.invest_return_id,
    )
    return message is not None


def refresh_invest_return_approval_messages(*, invest_return: InvestReturn) -> int:
    """
    Sync Telegram cards after decisions (same idea as refresh_request_messages for requests):
    update text/headers and drop inline buttons when the step is no longer actionable.
    """
    invest_return.refresh_from_db()
    blocked, current_step = _investment_flow_flags(invest_return=invest_return)
    approvals = list(
        InvestmentReturnApproval.objects.filter(
            invest_return=invest_return,
            telegram_message__isnull=False,
            approver_recipient_id__isnull=False,
        ).select_related("invest_return", "invest_return__company", "tenant", "approver_user", "telegram_message")
    )
    updated = 0
    dispatcher = TelegramDispatcher(invest_return.tenant)
    settings_obj = get_requests_messaging_gateway_settings(tenant=invest_return.tenant)
    for approval in approvals:
        readonly = _investment_telegram_card_should_be_readonly(
            approval=approval,
            blocked_by_rejection=blocked,
            current_pending_step=current_step,
        )
        if approval.telegram_message_id is None:
            continue
        message = dispatcher.edit(
            approval.telegram_message,
            action=settings_obj.edit_action,
            text=build_investment_return_approval_telegram_message(
                invest_return=invest_return,
                approval=approval,
                blocked_by_rejection=blocked,
                current_pending_step=current_step,
            ),
            buttons=_build_buttons(approval=approval) if not readonly else [],
            recipient_id=approval.approver_recipient_id,
            approval_id=approval.id,
            request_id=approval.invest_return_id,
        )
        if message is not None:
            updated += 1
    return updated


def deactivate_investment_return_approval_buttons(*, approval: InvestmentReturnApproval) -> bool:
    """editMessage with empty buttons — e.g. duplicate callback after decision."""
    if approval.telegram_message_id is None or approval.approver_recipient_id is None:
        return False
    dispatcher = TelegramDispatcher(approval.tenant)
    settings_obj = get_requests_messaging_gateway_settings(tenant=approval.tenant)
    message = dispatcher.deactivate(
        approval.telegram_message,
        action=settings_obj.edit_action,
        text=build_investment_return_approval_telegram_message(
            invest_return=approval.invest_return,
            approval=approval,
            blocked_by_rejection=False,
            current_pending_step=None,
        ),
        recipient_id=approval.approver_recipient_id,
        approval_id=approval.id,
        request_id=approval.invest_return_id,
    )
    return message is not None


def create_approvals_for_invest_return(*, invest_return: InvestReturn) -> int:
    config = resolve_investment_approval_config(
        tenant=invest_return.tenant,
        payout_type=invest_return.type,
        payout_recipient=invest_return.recipient,
    )
    if not config:
        return 0

    created = 0
    for step in config.steps.filter(is_enabled=True).select_related("telegram_chat").order_by("step", "id"):
        if step.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            approvers = list(step.approver_users.filter(is_active=True))
            record_user = approvers[0] if approvers else invest_return.created_by
            recipient_id = step.telegram_chat.chat_id if step.telegram_chat else None
            InvestmentReturnApproval.objects.create(
                tenant=invest_return.tenant,
                invest_return=invest_return,
                step=step.step,
                step_type=step.step_type,
                approver_user=record_user,
                approver_recipient_id=recipient_id,
                approver_external_user_id=record_user.telegram_from_id,
            )
            created += 1
            continue
        for approver in step.approver_users.filter(is_active=True):
            chat_id = step.telegram_chat.chat_id if step.telegram_chat else None
            user_chat_id = approver.telegram_chat_id
            recipient_id = (
                chat_id
                if step.step_type == InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION
                else (str(user_chat_id) if user_chat_id is not None else None)
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
        ).select_related("invest_return", "tenant", "approver_user")
    )
    any_notification_finalized = False
    for row in rows:
        if row.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            ok = _dispatch_approval_message(approval=row, include_buttons=False)
            if ok:
                now = timezone.now()
                updated = InvestmentReturnApproval.objects.filter(
                    pk=row.pk,
                    decision=InvestmentReturnApproval.DECISION_PENDING,
                ).update(
                    decision=InvestmentReturnApproval.DECISION_APPROVED,
                    decided_at=now,
                )
                if updated:
                    any_notification_finalized = True
        else:
            _dispatch_approval_message(approval=row, include_buttons=True)
    if any_notification_finalized:
        return route_invest_return_approvals(invest_return=invest_return)
    return len(rows)


def route_invest_return_approvals(*, invest_return: InvestReturn) -> int:
    refresh_invest_return_approval_messages(invest_return=invest_return)
    pending = InvestmentReturnApproval.objects.filter(
        tenant=invest_return.tenant,
        invest_return=invest_return,
        decision=InvestmentReturnApproval.DECISION_PENDING,
    ).exists()
    if not pending:
        has_any_approval = InvestmentReturnApproval.objects.filter(
            tenant=invest_return.tenant,
            invest_return=invest_return,
        ).exists()
        if not has_any_approval:
            return 0
        has_rejected = InvestmentReturnApproval.objects.filter(
            tenant=invest_return.tenant,
            invest_return=invest_return,
            decision=InvestmentReturnApproval.DECISION_REJECTED,
        ).exists()
        if has_rejected:
            if invest_return.confirmed:
                invest_return.confirmed = False
                invest_return.save(update_fields=["confirmed"])
            from apps.modules.investments.models import InvestPayoutSchedule
            InvestPayoutSchedule.objects.filter(created_return=invest_return).update(
                created_return=None,
                last_edit_at=timezone.now(),
            )
            return 0
        if not invest_return.confirmed:
            invest_return.confirmed = True
            invest_return.save(update_fields=["confirmed"])
        return 0
    return dispatch_pending_invest_return_approvals(invest_return=invest_return)


def reject_remaining_pending_invest_return_approvals(*, invest_return: InvestReturn) -> int:
    """После отказа: все ещё ожидающие строки по этой выплате → отказ (цепочка не идёт дальше)."""
    now = timezone.now()
    return InvestmentReturnApproval.objects.filter(
        invest_return=invest_return,
        decision=InvestmentReturnApproval.DECISION_PENDING,
    ).update(
        decision=InvestmentReturnApproval.DECISION_REJECTED,
        decision_comment=INVESTMENT_APPROVAL_CASCADE_REJECTION_COMMENT,
        decided_at=now,
        updated_at=now,
    )


def confirm_invest_return_approval_by_id(
    *,
    tenant,
    approval_id: int,
    approver_recipient_id: str | None = None,
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
        if approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            raise ValueError("Этап notification подтверждается автоматически после отправки сообщения.")
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

        if decision == InvestmentReturnApproval.DECISION_REJECTED:
            reject_remaining_pending_invest_return_approvals(invest_return=approval.invest_return)

        route_invest_return_approvals(invest_return=approval.invest_return)
        approval.invest_return.refresh_from_db()
        return InvestmentApprovalDecisionResult(approval=approval, invest_return=approval.invest_return)
