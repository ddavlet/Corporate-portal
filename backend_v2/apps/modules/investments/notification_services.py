from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.investments.services import (
    CbuRateFetchError,
    clamp_rate_date_to_cbu_availability,
    usd_uzs_equivalents,
)

logger = logging.getLogger(__name__)

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def build_payout_schedule_public_url(*, schedule) -> str:
    """Web-app deep link that opens the investments schedule for this tenant.

    Empty string when the tenant base URL cannot be resolved — callers then omit the
    link button (graceful degradation, same pattern as the requests module).
    """
    tenant = getattr(schedule, "tenant", None)
    subdomain = (getattr(tenant, "subdomain", "") or "").strip()
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    if not subdomain or not base_domain:
        return ""
    return f"https://{subdomain}.{base_domain}/app/investments?tab=schedule&schedule={schedule.pk}"


def recompute_payout_schedule_paid_status(*, schedule) -> None:
    """Roll confirmed linked payouts up into payment_amount; softly track the paid status.

    ``payment_amount`` = sum of confirmed InvestReturns linked to the schedule (always kept
    in sync). The coupling to ``is_paid`` is intentionally *soft*:

    * If the schedule was closed manually (``closed_manually=True``), ``is_paid`` is left
      untouched — a manual close stands even when under-paid and is never reopened by later
      payout changes.
    * Otherwise ``is_paid`` is auto-derived: it becomes True once the confirmed total reaches
      the scheduled amount (over-payment also closes it) and reflects reality if payouts later
      change. There is no cap — paying more or less than planned is allowed.

    Payouts in another currency are converted into the schedule's currency at the CBU rate
    on the payout date (see ``_linked_returns_total``). If a rate is unavailable the schedule
    is left as is rather than overwritten with a wrong total.

    Idempotent and safe to call repeatedly. Uses ``.update()`` so it never recurses through
    InvestReturn signals.
    """
    from apps.modules.investments.models import InvestPayoutSchedule

    row = (
        InvestPayoutSchedule.objects.filter(pk=schedule.pk)
        .values("amount", "currency", "closed_manually")
        .first()
    )
    if row is None:
        return

    try:
        paid = _linked_returns_total(
            schedule_id=schedule.pk, schedule_currency=row["currency"], confirmed_only=True
        )
    except CbuRateFetchError:
        logger.exception(
            "invest_schedule: cannot convert linked payouts for schedule=%s; paid status left unchanged",
            schedule.pk,
        )
        return
    fields = {"payment_amount": paid, "last_edit_at": timezone.now()}
    if not row["closed_manually"]:
        amount = _money(row["amount"])
        fields["is_paid"] = amount > 0 and paid >= amount
    InvestPayoutSchedule.objects.filter(pk=schedule.pk).update(**fields)


def _schedule_committed_amount(schedule) -> Decimal:
    """Sum of all (non-rejected) payouts already linked to the schedule.

    Rejected payouts are unlinked from the schedule (see approval routing), so every
    linked return — pending or confirmed — counts toward the committed total. The
    outstanding remainder is ``amount - committed``. Raises ``CbuRateFetchError`` when a
    foreign-currency payout cannot be converted.
    """
    return _linked_returns_total(
        schedule_id=schedule.pk, schedule_currency=schedule.currency, confirmed_only=False
    )


def _has_outstanding_remainder(schedule) -> bool:
    """True while linked payouts (converted to the schedule's currency) don't cover its amount.

    Without a rate the schedule counts as outstanding: a spare reminder beats a silent one.
    """
    try:
        committed = _schedule_committed_amount(schedule)
    except CbuRateFetchError:
        logger.exception("invest_notify: cannot compute remainder for schedule=%s", schedule.pk)
        return True
    return committed < _money(schedule.amount)


def _amount_in_schedule_currency(*, sum_val, currency: str, schedule_currency: str, payout_date) -> Decimal:
    """``sum_val`` in ``currency`` expressed in ``schedule_currency``.

    Same currency → as is; USD↔UZS → CBU rate from the archive (the same one the reports use):
    on the payout date, else the nearest earlier one — never the network, so a request or a
    cron reminder doesn't wait for cbu.uz. Raises ``CbuRateFetchError`` for an empty archive
    or an unsupported pair.
    """
    source = str(currency or "USD").strip().upper()
    target = str(schedule_currency or "USD").strip().upper()
    if source == target:
        return _money(sum_val)
    if {source, target} != {"USD", "UZS"}:
        raise CbuRateFetchError(f"Нет пересчёта {source} → {target}.")
    sum_usd, sum_uzs = usd_uzs_equivalents(
        sum_val=sum_val,
        currency=source,
        rate_date=clamp_rate_date_to_cbu_availability(requested=payout_date),
    )
    return _money(sum_usd if target == "USD" else sum_uzs)


def _linked_returns_total(*, schedule_id, schedule_currency: str, confirmed_only: bool) -> Decimal:
    """Sum of payouts linked to a schedule, each converted into the schedule's currency."""
    from apps.modules.investments.models import InvestReturn

    qs = InvestReturn.objects.filter(payout_schedule_id=schedule_id)
    if confirmed_only:
        qs = qs.filter(confirmed=True)
    total = Decimal("0.00")
    for row in qs.values("sum", "currency", "date"):
        total += _amount_in_schedule_currency(
            sum_val=row["sum"],
            currency=row["currency"],
            schedule_currency=schedule_currency,
            payout_date=row["date"],
        )
    return _money(total)


_poller_started = False
_poller_lock = threading.Lock()


def _payment_progress_lines(schedule) -> list[str]:
    """Paid / remaining lines, shown only once a partial payment exists on the schedule."""
    paid = _money(schedule.payment_amount)
    if paid <= 0:
        return []
    currency = escape(schedule.currency)
    remaining = _money(schedule.amount) - paid
    if remaining < 0:
        remaining = Decimal("0.00")
    return [
        f"Оплачено: {paid:,.2f} {currency}",
        f"Остаток: {remaining:,.2f} {currency}",
    ]


def _build_payout_notification_text(schedule) -> str:
    company_name = escape(schedule.company.name) if schedule.company else ""
    parts = ["<b>Напоминание о выплате по инвестициям</b>"]
    if company_name:
        parts.append(f"Компания: {company_name}")
    parts.append(f"Дата: {schedule.payout_date.strftime('%d.%m.%Y')}")
    parts.append(f"Сумма: {schedule.amount:,.2f} {escape(schedule.currency)}")
    parts.extend(_payment_progress_lines(schedule))
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
    parts.extend(_payment_progress_lines(schedule))
    if schedule.comment:
        parts.append(f"Примечание: {escape(schedule.comment)}")
    return "\n".join(parts)


def _payout_notification_buttons(schedule) -> list[list[dict]]:
    """Inline keyboard: the create-request callback button plus an optional web deep link."""
    rows: list[list[dict]] = [
        [{"label": "💳 Создать заявку", "value": f"invest_pay:{schedule.pk}"}]
    ]
    pay_url = build_payout_schedule_public_url(schedule=schedule)
    if pay_url:
        rows.append([{"label": "🔗 Открыть выплату", "url": pay_url}])
    return rows


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
        "buttons": _payout_notification_buttons(schedule),
    }
    result = post_messaging_gateway(tenant=config.tenant, payload=payload)
    return result is not None


def refresh_payout_notification_message(*, schedule, chat_id, message_id, note: str) -> bool:
    """Edit the reminder after an action: refresh the paid/remaining text, append a status
    note, and keep the action buttons only while an outstanding remainder still exists.

    Telegram's editMessageText removes the inline keyboard when reply_markup is omitted, which
    the gateway does when buttons=[]. Best-effort: failure here does not undo the created payout.
    """
    from apps.modules.telegram_approvals.services import get_tenant_bot_token, post_messaging_gateway

    if not message_id or not chat_id:
        return False
    bot_token = get_tenant_bot_token(schedule.tenant)
    if not bot_token:
        return False

    schedule.refresh_from_db()
    try:
        outstanding = _money(schedule.amount) - _schedule_committed_amount(schedule)
    except CbuRateFetchError:
        # Best-effort refresh: without a rate, keep the button while the schedule is open.
        logger.exception("invest_notify: cannot compute remainder for schedule=%s", schedule.pk)
        outstanding = _money(schedule.amount)
    keep_button = not schedule.is_paid and outstanding > 0
    text = f"{_build_payout_notification_text(schedule)}\n\n{escape(note)}"
    payload = {
        "action": "edit",
        "text": text,
        "recipient_id": str(chat_id),
        "bot_token": bot_token,
        "tenant_id": str(schedule.tenant_id),
        "message_id": int(message_id),
        "buttons": _payout_notification_buttons(schedule) if keep_button else [],
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
        # Remind only while an outstanding (uncommitted) remainder exists: keep nudging
        # through partial payments, stop once linked payouts cover the full amount.
        # The committed total is computed per schedule (not in SQL) so payouts in another
        # currency are converted at the CBU rate first — see _has_outstanding_remainder.
        outstanding = InvestPayoutSchedule.objects.filter(tenant=config.tenant, is_paid=False)
        # Upcoming payouts: due within the lead-time window and not yet fully committed.
        threshold_date = today + dt.timedelta(days=config.days_before)
        upcoming = outstanding.filter(
            payout_date__lte=threshold_date,
            payout_date__gte=today,
        ).select_related("company")
        for schedule in filter(_has_outstanding_remainder, upcoming):
            if _try_send(schedule=schedule, config=config, text=_build_payout_notification_text(schedule)):
                sent += 1

        # Overdue payouts: re-notify every N days until paid (0 disables this pass).
        if config.overdue_notify_every_days > 0:
            overdue = outstanding.filter(
                payout_date__lt=today,
            ).select_related("company")
            for schedule in filter(_has_outstanding_remainder, overdue):
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


def create_return_for_schedule(*, schedule, created_by, amount=None) -> tuple[object, bool, str]:
    """Atomically create a (possibly partial) InvestReturn for a payout schedule.

    The caller MUST wrap this in ``transaction.atomic()``. The schedule is re-fetched with
    ``SELECT FOR UPDATE OF self`` to serialize concurrent button presses.

    The link to the schedule is intentionally loose: ``amount`` defaults to the outstanding
    remainder (``amount - committed``) for the one-tap flow, but an explicit ``amount`` is
    *not* capped — over-payment is allowed, and paying less simply leaves the schedule open.
    Payouts may also be created with no schedule at all (out-of-band); this helper just covers
    the schedule-linked convenience path.

    Returns ``(invest_return_or_None, was_created, status_note)``.
    """
    from apps.modules.investments.models import InvestPayoutSchedule, InvestReturn
    from apps.modules.investments.approval_services import (
        create_approvals_for_invest_return,
        route_invest_return_approvals,
    )

    locked = (
        InvestPayoutSchedule.objects
        .select_for_update(of=("self",))
        .select_related("tenant", "company")
        .get(pk=schedule.pk)
    )
    if locked.is_paid:
        return None, False, "✅ Уже оплачено"
    if not locked.return_type or not locked.recipient:
        raise ValidationError(
            {"detail": "Укажите тип выплаты и получателя в расписании перед созданием."}
        )

    if amount is None:
        # One-tap default: bill whatever remains. Nothing to auto-bill once fully committed,
        # but an explicit amount can still be sent to over-pay.
        try:
            committed = _schedule_committed_amount(locked)
        except CbuRateFetchError as exc:
            logger.exception("invest_schedule: cannot compute remainder for schedule=%s", locked.pk)
            raise ValidationError(
                {"detail": f"Не удалось пересчитать выплаты в валюту расписания: {exc}. Укажите сумму вручную."}
            ) from exc
        outstanding = _money(locked.amount) - committed
        if outstanding <= 0:
            return None, False, "✅ Остаток по расписанию уже покрыт; укажите сумму, чтобы доплатить/переплатить."
        req_amount = outstanding
    else:
        req_amount = _money(amount)
        if req_amount <= 0:
            raise ValidationError({"amount": "Сумма должна быть больше нуля."})
        # No upper bound: over-payment vs the planned amount is allowed by design.

    billing_date = locked.payout_date.replace(day=1)
    invest_return = InvestReturn.objects.create(
        tenant=locked.tenant,
        company=locked.company,
        payout_schedule=locked,
        date=locked.payout_date,
        billing_date=billing_date,
        sum=req_amount,
        currency=locked.currency,
        comment=locked.comment or "",
        type=locked.return_type,
        recipient=locked.recipient,
        confirmed=False,
        created_by=created_by,
    )
    # Back-compat: keep created_return pointing at the first payout made from this schedule.
    if locked.created_return_id is None:
        InvestPayoutSchedule.objects.filter(pk=locked.pk, created_return__isnull=True).update(
            created_return=invest_return,
            last_edit_at=timezone.now(),
        )
    create_approvals_for_invest_return(invest_return=invest_return)
    route_invest_return_approvals(invest_return=invest_return)
    return invest_return, True, f"✅ Выплата #{invest_return.pk} создана на сумму {req_amount:.2f} {locked.currency}"


def link_returns_to_schedule(*, schedule, return_ids: list[int]) -> list:
    """Atomically link existing, unlinked InvestReturn rows to a payout schedule.

    The caller MUST wrap this in ``transaction.atomic()``. The schedule is re-fetched with
    ``SELECT FOR UPDATE OF self`` (same lock as ``create_return_for_schedule``) so this can't
    race a concurrent one-tap payout creation. Every requested id must exist, belong to the
    same tenant and company as the schedule, and not already be linked elsewhere — otherwise
    the whole call is rejected with a ``ValidationError`` naming the offending ids, so nothing
    is partially linked.

    Returns the list of now-linked ``InvestReturn`` instances.
    """
    from apps.modules.investments.models import InvestPayoutSchedule, InvestReturn

    locked = (
        InvestPayoutSchedule.objects
        .select_for_update(of=("self",))
        .select_related("tenant", "company")
        .get(pk=schedule.pk)
    )

    unique_ids = list(dict.fromkeys(return_ids))
    if not unique_ids:
        raise ValidationError({"return_ids": "Укажите хотя бы одну выплату."})

    candidates = list(
        InvestReturn.objects.select_for_update(of=("self",)).filter(
            pk__in=unique_ids, tenant_id=locked.tenant_id
        )
    )
    found_ids = {r.pk for r in candidates}
    missing = [rid for rid in unique_ids if rid not in found_ids]
    if missing:
        raise ValidationError({"return_ids": f"Выплаты не найдены: {missing}"})

    already_linked = [r.pk for r in candidates if r.payout_schedule_id is not None]
    if already_linked:
        raise ValidationError({"return_ids": f"Выплаты уже привязаны к расписанию: {already_linked}"})

    mismatched_company = [r.pk for r in candidates if r.company_id != locked.company_id]
    if mismatched_company:
        raise ValidationError(
            {"return_ids": f"Выплаты относятся к другой компании: {mismatched_company}"}
        )

    InvestReturn.objects.filter(pk__in=found_ids).update(
        payout_schedule=locked, last_edit_at=timezone.now()
    )
    recompute_payout_schedule_paid_status(schedule=locked)
    for r in candidates:
        r.payout_schedule_id = locked.pk
    return candidates


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
