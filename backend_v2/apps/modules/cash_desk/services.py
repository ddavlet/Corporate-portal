"""PAYED handler for cash requests: transfer revenue + «Движение денежных средств» message."""

from __future__ import annotations

import logging

from django.db import transaction

from apps.modules.cash_desk import messaging
from apps.modules.cash_desk.constants import TRANSFER_PURPOSE
from apps.modules.cash_desk.models import CashDeskMessage
from apps.modules.cash_desk.services_config import get_active_config
from apps.modules.cash_desk.transfer_revenue import (
    TransferDestinationError,
    ensure_transfer_revenue,
    resolve_transfer_destination,
)
from apps.modules.cashier.models import CashExpense
from apps.modules.requests.models import Request
from apps.modules.requests.payment_type_families import canonical_payment_type
from apps.modules.wallets.resolution import resolve_wallet_for_cash

logger = logging.getLogger(__name__)

NO_CHAT_ERROR = "Кассовая группа не выбрана"


def is_cash_request(request_obj) -> bool:
    return canonical_payment_type(request_obj.payment_type) == Request.PAYMENT_TYPE_CASH


def message_kind(request_obj) -> str:
    if (request_obj.payment_purpose or "").strip() == TRANSFER_PURPOSE:
        return CashDeskMessage.Kind.TRANSFER
    return CashDeskMessage.Kind.EXPENSE


def expense_wallet_for_request(request_obj):
    """Register the cash was actually paid from: the request's CashExpense wallet, else the default resolution."""
    expense = (
        CashExpense.objects.filter(tenant_id=request_obj.tenant_id, external_id=f"req-{request_obj.pk}")
        .select_related("wallet__cash_register")
        .order_by("pk")
        .first()
    )
    if expense is not None:
        return expense.wallet
    logger.warning(
        "cash_desk: no CashExpense req-%s, falling back to wallet resolution tenant_id=%s wallet_ref_id=%s",
        request_obj.pk, request_obj.tenant_id, request_obj.wallet_ref_id,
    )
    return resolve_wallet_for_cash(
        tenant=request_obj.tenant, currency=request_obj.currency, wallet_id=request_obj.wallet_ref_id
    )


def _create_transfer_revenue(*, request_obj, msg: CashDeskMessage) -> None:
    try:
        with transaction.atomic():
            destination = resolve_transfer_destination(request_obj)
            ensure_transfer_revenue(request_obj=request_obj, destination=destination)
    except TransferDestinationError as exc:
        msg.revenue_error = str(exc)
        logger.error(
            "cash_desk: transfer revenue not created request_id=%s tenant_id=%s reason=%s",
            request_obj.pk, request_obj.tenant_id, exc,
        )
    except Exception as exc:
        msg.revenue_error = f"Ошибка создания прихода: {exc}"
        logger.exception(
            "cash_desk: transfer revenue crashed request_id=%s tenant_id=%s", request_obj.pk, request_obj.tenant_id
        )


def _handle_payed(request_obj) -> None:
    if not is_cash_request(request_obj):
        return
    config = get_active_config(request_obj.tenant)
    if config is None:
        return

    kind = message_kind(request_obj)
    msg, created = CashDeskMessage.objects.get_or_create(
        request=request_obj,
        defaults={"tenant": request_obj.tenant, "kind": kind, "status": CashDeskMessage.Status.PENDING},
    )
    if not created:
        logger.info("cash_desk: repeated PAYED ignored request_id=%s message_id=%s", request_obj.pk, msg.pk)
        return

    if kind == CashDeskMessage.Kind.TRANSFER:
        _create_transfer_revenue(request_obj=request_obj, msg=msg)

    chat = config.telegram_chat
    if chat is None or not chat.is_active:
        msg.status = CashDeskMessage.Status.SKIPPED
        msg.error = NO_CHAT_ERROR
        msg.save(update_fields=["status", "error", "revenue_error", "updated_at"])
        logger.warning(
            "cash_desk: no active cash group, message skipped request_id=%s tenant_id=%s",
            request_obj.pk, request_obj.tenant_id,
        )
        return

    msg.save(update_fields=["revenue_error", "updated_at"])
    message_id = msg.pk
    transaction.on_commit(lambda: messaging.send_movement_message(message_id), robust=True)


def on_request_payed(*, request_obj) -> None:
    """Registered PAYED handler (see apps.CashDeskConfig.ready). Never breaks the payment flow.

    Own savepoint: `dispatch_request_payed_event_handlers` opens none, so a DB error here would
    otherwise abort the caller's transaction.
    """
    try:
        with transaction.atomic():
            _handle_payed(request_obj)
    except Exception:
        logger.exception(
            "cash_desk: payed handler failed request_id=%s tenant_id=%s",
            getattr(request_obj, "pk", None), getattr(request_obj, "tenant_id", None),
        )
