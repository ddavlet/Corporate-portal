"""Business logic for cash-withdrawal receipts."""

from __future__ import annotations

import logging

from django.db import transaction

from apps.modules.cash_withdrawals import formatter, messaging
from apps.modules.cash_withdrawals.models import CashWithdrawalConfig, CashWithdrawalReceipt

logger = logging.getLogger(__name__)


def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def get_active_config(tenant) -> CashWithdrawalConfig | None:
    return (
        CashWithdrawalConfig.objects.filter(tenant=tenant, is_active=True)
        .select_related("tenant", "card_telegram_chat", "alert_telegram_chat")
        .first()
    )


def find_rule(config, request_obj):
    payment_type = _norm(request_obj.payment_type)
    purpose = _norm(request_obj.payment_purpose)
    if not purpose:
        return None
    for rule in config.rules.select_related("wallet", "wallet__cash_register").all():
        if _norm(rule.payment_type) == payment_type and _norm(rule.payment_purpose) == purpose:
            return rule
    return None


def _send_cards_safely(receipt_id: int) -> None:
    receipt = (
        CashWithdrawalReceipt.objects.select_related("tenant", "request", "wallet", "wallet__cash_register")
        .filter(pk=receipt_id)
        .first()
    )
    if receipt is None:
        return
    try:
        messaging.send_receipt_cards(receipt)
    except Exception:
        logger.exception("cash_withdrawals: send_receipt_cards crashed receipt_id=%s", receipt_id)


def create_receipt_for_request(*, request_obj, send: bool = True) -> CashWithdrawalReceipt | None:
    config = get_active_config(request_obj.tenant)
    if config is None:
        return None
    rule = find_rule(config, request_obj)
    if rule is None:
        return None
    wallet = rule.wallet
    if _norm(request_obj.currency) != _norm(wallet.currency):
        logger.error(
            "cash_withdrawals: currency mismatch request_id=%s request_currency=%s wallet_id=%s wallet_currency=%s",
            request_obj.pk, request_obj.currency, wallet.pk, wallet.currency,
        )
        text = formatter.build_currency_mismatch_text(request_obj=request_obj, wallet=wallet)
        transaction.on_commit(
            lambda: messaging.send_to_alert_recipients(config=config, text=text, request_id=request_obj.pk)
        )
        return None
    receipt, created = CashWithdrawalReceipt.objects.get_or_create(
        request=request_obj,
        defaults={
            "tenant": request_obj.tenant,
            "wallet": wallet,
            "amount": request_obj.amount,
            "currency": request_obj.currency,
        },
    )
    if created:
        logger.info("cash_withdrawals: receipt created receipt_id=%s request_id=%s", receipt.pk, request_obj.pk)
        if send:
            receipt_id = receipt.pk
            transaction.on_commit(lambda: _send_cards_safely(receipt_id))
    return receipt


def on_request_payed(*, request_obj) -> None:
    """Registered PAYED handler (see apps.CashWithdrawalsConfig.ready).

    Runs in its own savepoint: `dispatch_request_payed_event_handlers` catches exceptions
    but opens no savepoint (unlike its REJECTED counterpart), so a DB error raised here
    would otherwise leave Postgres in an aborted-transaction state and break the caller's
    PAYED status save.
    """
    with transaction.atomic():
        create_receipt_for_request(request_obj=request_obj)
