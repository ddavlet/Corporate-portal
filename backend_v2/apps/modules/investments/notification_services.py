from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from html import escape
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")
_NOTIFY_DAILY_HOUR = 9  # 09:00 Tashkent

_poller_started = False
_poller_lock = threading.Lock()


def _build_payout_notification_text(schedule) -> str:
    company_name = escape(schedule.company.name) if schedule.company else ""
    parts = ["<b>Investment payout reminder</b>"]
    if company_name:
        parts.append(f"Company: {company_name}")
    parts.append(f"Date: {schedule.payout_date.strftime('%d.%m.%Y')}")
    parts.append(f"Amount: {schedule.amount:,.2f} {escape(schedule.currency)}")
    if schedule.comment:
        parts.append(f"Note: {escape(schedule.comment)}")
    return "\n".join(parts)


def _send_payout_notification(*, schedule, config) -> bool:
    from apps.modules.telegram_approvals.services import _get_tenant_bot_token, post_messaging_gateway

    user = config.responsible_user
    chat_id = getattr(user, "telegram_chat_id", None)
    if not chat_id:
        logger.warning(
            "invest_notify: responsible_user=%s has no telegram_chat_id, skipping schedule=%s",
            user.pk,
            schedule.pk,
        )
        return False

    bot_token = _get_tenant_bot_token(config.tenant)
    if not bot_token:
        logger.warning("invest_notify: tenant=%s has no Telegram bot token, skipping", config.tenant_id)
        return False

    text = _build_payout_notification_text(schedule)
    payload = {
        "action": "send_interactive",
        "text": text,
        "recipient_id": str(chat_id),
        "bot_token": bot_token,
        "tenant_id": str(config.tenant_id),
        "buttons": [[{"label": "💳 Create Payment", "value": f"invest_pay:{schedule.pk}"}]],
    }
    result = post_messaging_gateway(tenant=config.tenant, payload=payload)
    return result is not None


def remove_payout_notification_button(*, schedule, chat_id, message_id, note: str) -> bool:
    """Edit the Telegram notification to drop the 'Create Payment' button and append a status note.

    Telegram's editMessageText removes the inline keyboard when reply_markup is omitted, which the
    gateway does when buttons=[]. Best-effort: failure here does not undo the created request.
    """
    from apps.modules.telegram_approvals.services import _get_tenant_bot_token, post_messaging_gateway

    if not message_id or not chat_id:
        return False
    bot_token = _get_tenant_bot_token(schedule.tenant)
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
    sent = 0

    configs = (
        InvestNotificationConfig.objects.filter(is_active=True)
        .select_related("tenant", "responsible_user")
    )

    for config in configs:
        threshold_date = today + dt.timedelta(days=config.days_before)
        schedules = InvestPayoutSchedule.objects.filter(
            tenant=config.tenant,
            is_paid=False,
            payout_date__lte=threshold_date,
            payout_date__gte=today,
        ).select_related("company")

        for schedule in schedules:
            # Create-first idempotency: the unique (schedule, recipient_user, sent_date)
            # constraint atomically picks a single winner, even across gunicorn workers
            # whose poller threads all wake at the same time. Only the creator sends.
            log, created = InvestPayoutNotificationLog.objects.get_or_create(
                schedule=schedule,
                recipient_user=config.responsible_user,
                sent_date=today,
            )
            if not created:
                continue

            try:
                ok = _send_payout_notification(schedule=schedule, config=config)
                if ok:
                    sent += 1
                else:
                    # Free the slot so a later run can retry.
                    log.delete()
            except Exception:
                logger.exception(
                    "invest_notify: failed to send notification schedule=%s tenant=%s",
                    schedule.pk,
                    config.tenant_id,
                )
                log.delete()

    return sent


def create_request_from_payout_schedule(*, schedule, created_by):
    from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
    from apps.modules.requests.approval_workflow import _recalculate_request_status, route_request_approvals
    from apps.modules.requests.models import Request

    with transaction.atomic():
        company_name = schedule.company.name if schedule.company else ""
        req = Request.objects.create(
            tenant=schedule.tenant,
            created_by=created_by,
            vendor=company_name,
            title=(schedule.tenant.name or "").strip()[:200],
            description=schedule.comment or "",
            amount=schedule.amount,
            currency=schedule.currency,
            payment_type="Перечисление",
            urgency="Обычно",
            requester=created_by,
            payment_purpose="Investment payout",
            submitted_at=timezone.now(),
            status=Request.STATUS_DRAFT,
            billing_date=schedule.payout_date,
        )
        n = create_approval_rows_for_request(req)
        if n:
            if req.status == Request.STATUS_DRAFT:
                _recalculate_request_status(req)
            route_request_approvals(request_obj=req)
    return req


def _next_notify_run_at(now_dt: dt.datetime) -> dt.datetime:
    local_now = timezone.localtime(now_dt, TASHKENT_TZ)
    run_at_local = local_now.replace(hour=_NOTIFY_DAILY_HOUR, minute=0, second=0, microsecond=0)
    if local_now >= run_at_local:
        run_at_local += dt.timedelta(days=1)
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
