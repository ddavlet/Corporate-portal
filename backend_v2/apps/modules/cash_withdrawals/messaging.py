"""All tg-gateway I/O for cash-withdrawal receipts. Failures are logged, never raised."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from apps.modules.cash_withdrawals import formatter
from apps.modules.cash_withdrawals.models import CashWithdrawalMessage
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.tenants.models import TenantMembership

logger = logging.getLogger(__name__)
User = get_user_model()


def _active_member_ids(tenant_id: int) -> set[int]:
    return set(
        TenantMembership.objects.filter(tenant_id=tenant_id, is_active=True).values_list("user_id", flat=True)
    )


def confirmer_users(config) -> list:
    member_ids = _active_member_ids(config.tenant_id)
    users = User.objects.filter(cash_withdrawal_confirmer_rows__config=config, is_active=True).order_by("id")
    return [u for u in users if u.id in member_ids]


def alert_users(config) -> list:
    member_ids = _active_member_ids(config.tenant_id)
    users = User.objects.filter(cash_withdrawal_alert_rows__config=config, is_active=True).order_by("id")
    return [u for u in users if u.id in member_ids]


def _targets(*, chat, users) -> list[tuple[str, int | None]]:
    """Group chat when configured and active, otherwise each user's personal chat."""
    if chat is not None and chat.is_active:
        return [(str(chat.chat_id), None)]
    return [(str(u.telegram_chat_id), u.telegram_from_id) for u in users if u.telegram_chat_id]


def _send(*, tenant, recipient_id: str, external_user_id, text: str, buttons, request_id):
    settings_obj = get_requests_messaging_gateway_settings(tenant=tenant)
    try:
        return TelegramDispatcher(tenant).send(
            action=settings_obj.send_action,
            recipient_id=recipient_id,
            text=text,
            buttons=buttons,
            external_user_id=external_user_id,
            request_id=request_id,
        )
    except Exception:
        logger.exception(
            "cash_withdrawals: send failed tenant_id=%s recipient=%s request_id=%s",
            getattr(tenant, "pk", None), recipient_id, request_id,
        )
        return None


def send_receipt_cards(receipt) -> int:
    config = receipt.tenant.cash_withdrawal_config
    confirmers = confirmer_users(config)
    text = formatter.build_card_text(receipt=receipt, confirmers=confirmers)
    buttons = formatter.card_buttons(receipt)
    sent = 0
    targets = _targets(chat=config.card_telegram_chat, users=confirmers)
    if not targets:
        logger.error("cash_withdrawals: no card recipients receipt_id=%s tenant_id=%s", receipt.pk, receipt.tenant_id)
    for recipient_id, external_user_id in targets:
        message = _send(
            tenant=receipt.tenant,
            recipient_id=recipient_id,
            external_user_id=external_user_id,
            text=text,
            buttons=buttons,
            request_id=receipt.request_id,
        )
        if message is None:
            logger.error("cash_withdrawals: card not delivered receipt_id=%s recipient=%s", receipt.pk, recipient_id)
            continue
        CashWithdrawalMessage.objects.create(
            receipt=receipt, telegram_message=message, kind=CashWithdrawalMessage.Kind.CARD
        )
        sent += 1
    return sent


def refresh_receipt_cards(receipt) -> int:
    """Re-render every card of the receipt; non-pending cards lose the button."""
    from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt

    config = receipt.tenant.cash_withdrawal_config
    text = formatter.build_card_text(receipt=receipt, confirmers=confirmer_users(config))
    edit_action = get_requests_messaging_gateway_settings(tenant=receipt.tenant).edit_action
    dispatcher = TelegramDispatcher(receipt.tenant)
    updated = 0
    rows = receipt.messages.filter(kind=CashWithdrawalMessage.Kind.CARD).select_related("telegram_message")
    for row in rows:
        try:
            if receipt.status == CashWithdrawalReceipt.Status.PENDING:
                result = dispatcher.edit(
                    row.telegram_message, action=edit_action, text=text, buttons=formatter.card_buttons(receipt)
                )
            else:
                result = dispatcher.deactivate(row.telegram_message, action=edit_action, text=text)
        except Exception:
            logger.exception("cash_withdrawals: card refresh failed receipt_id=%s message_row=%s", receipt.pk, row.pk)
            continue
        if result is None:
            logger.error("cash_withdrawals: card refresh not delivered receipt_id=%s message_row=%s", receipt.pk, row.pk)
            continue
        updated += 1
    return updated


def send_to_alert_recipients(*, config, text: str, request_id=None) -> int:
    sent = 0
    for recipient_id, external_user_id in _targets(chat=config.alert_telegram_chat, users=alert_users(config)):
        if _send(
            tenant=config.tenant,
            recipient_id=recipient_id,
            external_user_id=external_user_id,
            text=text,
            buttons=[],
            request_id=request_id,
        ) is not None:
            sent += 1
    return sent


def send_alert(*, receipt, config, days: int) -> int:
    text = formatter.build_alert_text(receipt=receipt, days=days, responsible=confirmer_users(config))
    sent = 0
    for recipient_id, external_user_id in _targets(chat=config.alert_telegram_chat, users=alert_users(config)):
        message = _send(
            tenant=receipt.tenant,
            recipient_id=recipient_id,
            external_user_id=external_user_id,
            text=text,
            buttons=[],
            request_id=receipt.request_id,
        )
        if message is None:
            continue
        CashWithdrawalMessage.objects.create(
            receipt=receipt, telegram_message=message, kind=CashWithdrawalMessage.Kind.ALERT
        )
        sent += 1
    return sent


def reply_denied(*, tenant, recipient_id) -> None:
    if not recipient_id:
        return
    _send(
        tenant=tenant,
        recipient_id=str(recipient_id),
        external_user_id=None,
        text=formatter.DENIED_TEXT,
        buttons=[],
        request_id=None,
    )
