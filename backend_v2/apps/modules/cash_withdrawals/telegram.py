"""Telegram callback `cwr:<receipt_id>` — confirm that withdrawn cash reached the register."""

from __future__ import annotations

import logging

from apps.modules.cash_withdrawals import formatter, messaging
from apps.modules.cash_withdrawals.models import CashWithdrawalConfig, CashWithdrawalReceipt
from apps.modules.cash_withdrawals.services import confirm_receipt, find_confirmer_user

logger = logging.getLogger(__name__)


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def handle_callback(*, payload: str, event_data: dict) -> tuple[int, dict]:
    receipt_id = _int_or_none(payload[len(formatter.CALLBACK_PREFIX):])
    if receipt_id is None:
        return 400, {"detail": "Invalid cwr callback."}
    receipt = CashWithdrawalReceipt.objects.select_related("tenant").filter(pk=receipt_id).first()
    if receipt is None:
        logger.warning("cwr_callback: receipt_id=%s not found", receipt_id)
        return 404, {"detail": "Receipt not found."}

    recipient_id = event_data.get("recipient_id")
    tg_user_id = _int_or_none(event_data.get("user_id"))
    config = CashWithdrawalConfig.objects.filter(tenant_id=receipt.tenant_id).first()
    user = find_confirmer_user(config, tg_user_id) if (config and tg_user_id is not None) else None
    if user is None:
        logger.warning(
            "cwr_callback: denied user_id=%s receipt_id=%s tenant_id=%s",
            event_data.get("user_id"), receipt_id, receipt.tenant_id,
        )
        messaging.reply_denied(tenant=receipt.tenant, recipient_id=recipient_id)
        return 403, {"detail": "Not authorized."}

    receipt, created = confirm_receipt(receipt_id=receipt_id, user=user)
    if not created:
        receipt = (
            CashWithdrawalReceipt.objects.select_related(
                "tenant", "request", "wallet", "wallet__cash_register", "confirmed_by"
            ).get(pk=receipt_id)
        )
        messaging.refresh_receipt_cards(receipt)
        return 200, {"detail": "already_processed", "status": receipt.status}
    return 201, {"detail": "confirmed", "cash_revenue_id": receipt.cash_revenue_id}
