"""tg-gateway I/O for «Движение денежных средств». Failures are logged and recorded, never raised."""

from __future__ import annotations

import logging

from apps.modules.cash_desk.formatter import build_movement_text
from apps.modules.cash_desk.models import CashDeskMessage
from apps.modules.cash_desk.services_config import get_active_config
from apps.modules.cash_desk.transfer_revenue import TransferDestinationError, resolve_transfer_destination
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import balances_for_tenant_channel

logger = logging.getLogger(__name__)

NO_MESSAGE_ID_ERROR = "Шлюз не вернул message_id"


def _mark(msg: CashDeskMessage, *, status: str, error: str = "", telegram_message=None) -> None:
    msg.status = status
    msg.error = error
    fields = ["status", "error", "updated_at"]
    if telegram_message is not None:
        msg.telegram_message = telegram_message
        fields.append("telegram_message")
    msg.save(update_fields=fields)


def _destination(request_obj):
    try:
        return resolve_transfer_destination(request_obj)
    except TransferDestinationError:
        return None


def _deliver(msg: CashDeskMessage) -> None:
    from apps.modules.cash_desk.services import NO_CHAT_ERROR, expense_wallet_for_request

    request_obj = msg.request
    tenant = msg.tenant
    config = get_active_config(tenant)
    chat = config.telegram_chat if config is not None else None
    if chat is None or not chat.is_active:
        _mark(msg, status=CashDeskMessage.Status.SKIPPED, error=NO_CHAT_ERROR)
        logger.warning("cash_desk: no active cash group at send time message_id=%s", msg.pk)
        return

    kind = CashDeskMessage.Kind(msg.kind)
    revenue_error = msg.revenue_error or None
    destination = (
        _destination(request_obj) if kind == CashDeskMessage.Kind.TRANSFER and not revenue_error else None
    )
    text = build_movement_text(
        request_obj=request_obj,
        kind=kind,
        from_wallet=expense_wallet_for_request(request_obj),
        destination=destination,
        balances=balances_for_tenant_channel(tenant_id=tenant.pk, wallet_type=Wallet.Type.CASH),
        revenue_error=revenue_error,
    )
    telegram_message = TelegramDispatcher(tenant).send(
        action=get_requests_messaging_gateway_settings(tenant=tenant).send_action,
        recipient_id=str(chat.chat_id),
        text=text,
        request_id=request_obj.pk,
    )
    if telegram_message is None:
        _mark(msg, status=CashDeskMessage.Status.FAILED, error=NO_MESSAGE_ID_ERROR)
        logger.error("cash_desk: message not delivered message_id=%s request_id=%s", msg.pk, request_obj.pk)
        return
    _mark(msg, status=CashDeskMessage.Status.SENT, telegram_message=telegram_message)


def send_movement_message(message_id: int) -> None:
    try:
        msg = CashDeskMessage.objects.select_related("request", "tenant").filter(pk=message_id).first()
        if msg is None or msg.status != CashDeskMessage.Status.PENDING:
            return
        try:
            _deliver(msg)
        except Exception as exc:
            logger.exception("cash_desk: send failed message_id=%s request_id=%s", message_id, msg.request_id)
            _mark(msg, status=CashDeskMessage.Status.FAILED, error=str(exc) or exc.__class__.__name__)
    except Exception:
        logger.exception("cash_desk: send_movement_message crashed message_id=%s", message_id)
