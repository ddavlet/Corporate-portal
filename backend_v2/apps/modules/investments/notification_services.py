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
    # TODO: заменить на выбор из справочника чатов компании
    chat_id = config.chat_id or getattr(user, "telegram_chat_id", None)
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
        .select_related("tenant", "responsible_user")
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
            created_request__isnull=True,
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
                created_request__isnull=True,
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


def create_or_get_request_for_schedule(*, schedule, created_by) -> tuple[object, bool, str]:
    """Atomically create-or-return the payment Request linked to a payout schedule.

    The caller MUST wrap this in ``transaction.atomic()``. The function re-fetches the
    schedule with ``SELECT FOR UPDATE OF self`` to serialize concurrent button presses —
    the ``created_request`` FK then acts as the dupe gate.

    Returns ``(request_or_None, was_created, status_note)``.
    """
    from apps.modules.investments.models import InvestPayoutSchedule

    # select_related("tenant", "company"): fresh data for the Request creation below
    # (avoids using the caller's potentially-stale view of the schedule).
    locked = (
        InvestPayoutSchedule.objects
        .select_for_update(of=("self",))
        .select_related("tenant", "company")
        .get(pk=schedule.pk)
    )
    if locked.is_paid:
        return locked.created_request, False, "✅ Уже оплачено"
    if locked.created_request_id is not None:
        return locked.created_request, False, f"✅ Заявка #{locked.created_request_id} уже создана"
    req = create_request_from_payout_schedule(schedule=locked, created_by=created_by)
    # Single targeted UPDATE: no full save(), no need to refresh in-memory schedule.
    InvestPayoutSchedule.objects.filter(pk=locked.pk).update(
        created_request=req,
        last_edit_at=timezone.now(),
    )
    return req, True, f"✅ Заявка #{req.pk} создана"


def create_request_from_payout_schedule(*, schedule, created_by):
    from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
    from apps.modules.requests.approval_workflow import _recalculate_request_status, route_request_approvals
    from apps.modules.requests.models import Request

    with transaction.atomic():
        company_name = schedule.company.name if schedule.company else ""
        # No title= — Request.save() always overwrites it from the tenant name.
        req = Request.objects.create(
            tenant=schedule.tenant,
            created_by=created_by,
            vendor=company_name,
            description=schedule.comment or "",
            amount=schedule.amount,
            currency=schedule.currency,
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            requester=created_by,
            payment_purpose="Выплата по инвестициям",
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
