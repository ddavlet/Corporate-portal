from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from html import escape
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")

_poller_started = False
_poller_lock = threading.Lock()


def _build_payout_notification_text(schedule) -> str:
    company_name = escape(schedule.company.name) if schedule.company else ""
    parts = ["<b>Напоминание о выплате по инвестициям</b>"]
    if company_name:
        parts.append(f"Компания: {company_name}")
    parts.append(f"Дата: {schedule.payout_date.strftime('%d.%m.%Y')}")
    parts.append(f"Сумма: {schedule.amount:,.2f} {escape(schedule.currency)}")
    if schedule.comment:
        parts.append(f"Примечание: {escape(schedule.comment)}")
    return "\n".join(parts)


def _build_overdue_notification_text(schedule, days_overdue: int) -> str:
    company_name = escape(schedule.company.name) if schedule.company else ""
    parts = ["⚠️ <b>Просроченная выплата по инвестициям</b>"]
    if company_name:
        parts.append(f"Компания: {company_name}")
    parts.append(f"Срок оплаты: {schedule.payout_date.strftime('%d.%m.%Y')}")
    parts.append(f"Просрочка: {days_overdue} дн.")
    parts.append(f"Сумма: {schedule.amount:,.2f} {escape(schedule.currency)}")
    if schedule.comment:
        parts.append(f"Примечание: {escape(schedule.comment)}")
    return "\n".join(parts)


def _dispatch_payout_notification(*, schedule, config, text: str) -> bool:
    """Send an interactive Telegram message carrying the 'Create Payment' button. Shared by
    the upcoming and overdue flows — they differ only in the message text."""
    from apps.modules.telegram_approvals.services import get_tenant_bot_token, post_messaging_gateway

    user = config.responsible_user
    chat_id = config.telegram_chat.chat_id if config.telegram_chat else getattr(user, "telegram_chat_id", None)
    if not chat_id:
        logger.warning(
            "invest_notify: responsible_user=%s has no telegram_chat_id and config has no chat_id, skipping schedule=%s",
            user.pk,
            schedule.pk,
        )
        return False

    bot_token = get_tenant_bot_token(config.tenant)
    if not bot_token:
        logger.warning("invest_notify: tenant=%s has no Telegram bot token, skipping", config.tenant_id)
        return False

    payload = {
        "action": "send_interactive",
        "text": text,
        "recipient_id": str(chat_id),
        "bot_token": bot_token,
        "tenant_id": str(config.tenant_id),
        "buttons": [[{"label": "💳 Создать заявку", "value": f"invest_pay:{schedule.pk}"}]],
    }
    result = post_messaging_gateway(tenant=config.tenant, payload=payload)
    return result is not None


def remove_payout_notification_button(*, schedule, chat_id, message_id, note: str) -> bool:
    """Edit the Telegram notification to drop the 'Create Payment' button and append a status note.

    Telegram's editMessageText removes the inline keyboard when reply_markup is omitted, which the
    gateway does when buttons=[]. Best-effort: failure here does not undo the created request.
    """
    from apps.modules.telegram_approvals.services import get_tenant_bot_token, post_messaging_gateway

    if not message_id or not chat_id:
        return False
    bot_token = get_tenant_bot_token(schedule.tenant)
    if not bot_token:
        return False

    text = f"{_build_payout_notification_text(schedule)}\n\n{escape(note)}"
    payload = {
        "action": "edit",
        "text": text,
        "recipient_id": str(chat_id),
        "bot_token": bot_token,
        "tenant_id": str(schedule.tenant_id),
        "message_id": int(message_id),
        "buttons": [],
    }
    result = post_messaging_gateway(tenant=schedule.tenant, payload=payload)
    return result is not None


def process_due_invest_payout_notifications(*, now_dt: dt.datetime | None = None) -> int:
    from apps.modules.investments.models import InvestNotificationConfig, InvestPayoutNotificationLog, InvestPayoutSchedule

    now_dt = now_dt or timezone.now()
    today = now_dt.date()
    local_hour = timezone.localtime(now_dt, TASHKENT_TZ).hour
    sent = 0

    configs = (
        InvestNotificationConfig.objects.filter(is_active=True)
        .select_related("tenant", "responsible_user", "telegram_chat")
    )

    def _try_send(*, schedule, config, text: str) -> bool:
        # Create-first idempotency: the unique (schedule, recipient_user, sent_date)
        # constraint atomically picks a single winner, even across gunicorn workers whose
        # poller threads all wake at the same time. Only the creator sends.
        log, created = InvestPayoutNotificationLog.objects.get_or_create(
            schedule=schedule,
            recipient_user=config.responsible_user,
            sent_date=today,
        )
        if not created:
            return False
        try:
            if _dispatch_payout_notification(schedule=schedule, config=config, text=text):
                return True
            log.delete()  # free the slot so a later run can retry
        except Exception:
            logger.exception(
                "invest_notify: failed to send notification schedule=%s tenant=%s",
                schedule.pk,
                config.tenant_id,
            )
            log.delete()
        return False

    for config in configs:
        if local_hour != config.notify_hour:
            continue
        # Upcoming payouts: due within the lead-time window and not yet acted on.
        threshold_date = today + dt.timedelta(days=config.days_before)
        upcoming = InvestPayoutSchedule.objects.filter(
            tenant=config.tenant,
            is_paid=False,
            created_return__isnull=True,
            payout_date__lte=threshold_date,
            payout_date__gte=today,
        ).select_related("company")
        for schedule in upcoming:
            if _try_send(schedule=schedule, config=config, text=_build_payout_notification_text(schedule)):
                sent += 1

        # Overdue payouts: re-notify every N days until paid (0 disables this pass).
        if config.overdue_notify_every_days > 0:
            overdue = InvestPayoutSchedule.objects.filter(
                tenant=config.tenant,
                is_paid=False,
                created_return__isnull=True,
                payout_date__lt=today,
            ).select_related("company")
            for schedule in overdue:
                days_overdue = (today - schedule.payout_date).days
                if days_overdue % config.overdue_notify_every_days != 0:
                    continue
                if _try_send(
                    schedule=schedule,
                    config=config,
                    text=_build_overdue_notification_text(schedule, days_overdue),
                ):
                    sent += 1

    return sent


def create_or_get_return_for_schedule(*, schedule, created_by) -> tuple[object, bool, str]:
    """Atomically create-or-return the InvestReturn linked to a payout schedule.

    The caller MUST wrap this in ``transaction.atomic()``. The function re-fetches the
    schedule with ``SELECT FOR UPDATE OF self`` to serialize concurrent button presses —
    the ``created_return`` FK then acts as the dupe gate.

    Returns ``(invest_return_or_None, was_created, status_note)``.
    """
    from apps.modules.investments.models import InvestPayoutSchedule, InvestReturn
    from apps.modules.investments.approval_services import (
        create_approvals_for_invest_return,
        route_invest_return_approvals,
    )
    import datetime as dt

    locked = (
        InvestPayoutSchedule.objects
        .select_for_update(of=("self",))
        .select_related("tenant", "company")
        .get(pk=schedule.pk)
    )
    if locked.is_paid:
        return locked.created_return, False, "✅ Уже оплачено"
    if locked.created_return_id is not None:
        return locked.created_return, False, f"✅ Выплата #{locked.created_return_id} уже создана"
    if not locked.return_type or not locked.recipient:
        raise ValidationError(
            {"detail": "Укажите тип выплаты и получателя в расписании перед созданием."}
        )
    billing_date = locked.payout_date.replace(day=1)
    invest_return = InvestReturn.objects.create(
        tenant=locked.tenant,
        company=locked.company,
        date=locked.payout_date,
        billing_date=billing_date,
        sum=locked.amount,
        currency=locked.currency,
        comment=locked.comment or "",
        type=locked.return_type,
        recipient=locked.recipient,
        confirmed=False,
        created_by=created_by,
    )
    InvestPayoutSchedule.objects.filter(pk=locked.pk).update(
        created_return=invest_return,
        last_edit_at=timezone.now(),
    )
    create_approvals_for_invest_return(invest_return=invest_return)
    route_invest_return_approvals(invest_return=invest_return)
    return invest_return, True, f"✅ Выплата #{invest_return.pk} создана"


def _next_notify_run_at(now_dt: dt.datetime) -> dt.datetime:
    from apps.modules.investments.models import InvestNotificationConfig
    hours = set(
        InvestNotificationConfig.objects.filter(is_active=True)
        .values_list("notify_hour", flat=True)
        .distinct()
    ) or {9}
    local_now = timezone.localtime(now_dt, TASHKENT_TZ)
    future = sorted(h for h in hours if h > local_now.hour)
    if future:
        run_at_local = local_now.replace(hour=future[0], minute=0, second=0, microsecond=0)
    else:
        run_at_local = (local_now + dt.timedelta(days=1)).replace(
            hour=min(hours), minute=0, second=0, microsecond=0
        )
    return run_at_local.astimezone(now_dt.tzinfo)


def _poller_loop() -> None:
    while True:
        now_dt = timezone.now()
        next_run_at = _next_notify_run_at(now_dt)
        sleep_seconds = max((next_run_at - now_dt).total_seconds(), 0)
        time.sleep(sleep_seconds)
        try:
            process_due_invest_payout_notifications()
        except Exception:
            logger.exception("invest_notify: poller error")


def start_invest_notification_poller() -> None:
    global _poller_started
    with _poller_lock:
        if _poller_started:
            return
        _poller_started = True
    threading.Thread(target=_poller_loop, name="invest-notify-poller", daemon=True).start()
