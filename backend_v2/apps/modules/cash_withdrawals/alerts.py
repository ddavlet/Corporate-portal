"""Overdue alerts for pending cash-withdrawal receipts (run hourly by backend_cron)."""

from __future__ import annotations

import datetime as dt
import logging

from django.db.models import F
from django.utils import timezone

from apps.modules.cash_withdrawals import messaging
from apps.modules.cash_withdrawals.models import CashWithdrawalConfig, CashWithdrawalReceipt

logger = logging.getLogger(__name__)


def _local_date(value: dt.datetime) -> dt.date:
    return timezone.localtime(value).date()


def process_due_alerts(*, now_dt: dt.datetime | None = None) -> int:
    now = now_dt or timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    sent_total = 0
    configs = CashWithdrawalConfig.objects.filter(is_active=True).select_related("tenant", "alert_telegram_chat")
    for config in configs:
        if local_now.hour != config.alert_hour:
            continue
        pending = (
            CashWithdrawalReceipt.objects.filter(tenant_id=config.tenant_id, status=CashWithdrawalReceipt.Status.PENDING)
            .select_related("tenant", "request", "wallet", "wallet__cash_register")
            .order_by("id")
        )
        for receipt in pending:
            days = (today - _local_date(receipt.created_at)).days
            if days < config.alert_after_days:
                continue
            if receipt.last_alert_at and (today - _local_date(receipt.last_alert_at)).days < config.alert_repeat_every_days:
                continue
            try:
                delivered = messaging.send_alert(receipt=receipt, config=config, days=days)
            except Exception:
                logger.exception("cash_withdrawals: alert crashed receipt_id=%s", receipt.pk)
                continue
            if delivered == 0:
                logger.error("cash_withdrawals: alert not delivered receipt_id=%s tenant_id=%s", receipt.pk, config.tenant_id)
                continue
            CashWithdrawalReceipt.objects.filter(pk=receipt.pk).update(
                last_alert_at=now, alert_count=F("alert_count") + 1
            )
            sent_total += 1
    return sent_total
