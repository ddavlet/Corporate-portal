"""Telegram alerts to the owner only, deduplicated. Failures are logged, never raised.

Each alert is sent by the Telegram bot of the tenant whose account it is about; the
recipient (the owner) comes from KapitalbankAlertSettings.

Dedup of keyed alerts (``dedup_key``): the SyncEvent row is created first, inside a
savepoint, so the unique constraint arbitrates races (IntegrityError = someone else already
sent/is sending). If the send then fails, the row is not deleted (CLAUDE.md: no data
deletion); its ``dedup_key`` is set to NULL and the payload marked ``failed`` so a later
retry can claim the key again. Time-based alerts (mismatch/down) dedup through the
timestamps on AccountSyncState, which are only advanced after a successful send.
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.services import TelegramDispatcher, TelegramDispatchMissingMessageId

from .client import StatementDoc
from .models import AccountSyncState, BankAccountLink, KapitalbankAlertSettings, SyncEvent

logger = logging.getLogger(__name__)

REPEAT_AFTER = timedelta(hours=24)


def format_amount(value: Decimal) -> str:
    """'-361 569 643,41': space thousands separator, comma decimals, always two decimals."""
    text = f"{Decimal(value):,.2f}"
    return text.replace(",", " ").replace(".", ",")


def _money(value: Decimal, link: BankAccountLink) -> str:
    """format_amount plus the wallet currency when it is not UZS (UZS texts stay unchanged)."""
    text = format_amount(value)
    try:
        wallet = link.wallet()
    except ObjectDoesNotExist:
        wallet = None
    currency = (getattr(wallet, "currency", "") or "").strip()
    if currency and currency != "UZS":
        text = f"{text} {_esc(currency)}"
    return text


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


def _account_label(link: BankAccountLink) -> str:
    return f"{link.name or link.account_no} · …{link.account_no[-4:]}"


def _fmt_time(value: datetime) -> str:
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def _send_text(*, tenant, recipient_id: str, text: str) -> bool:
    """True when the gateway accepted the message. With require_message_id the dispatcher
    tells the cases apart: None = gateway unreachable or non-OK response (failed);
    TelegramDispatchMissingMessageId = OK response without message_id (sent, nothing to
    persist on our side)."""
    try:
        gateway = get_requests_messaging_gateway_settings(tenant=tenant)
        message = TelegramDispatcher(tenant).send(
            action=gateway.send_action, recipient_id=recipient_id, text=text, buttons=None, require_message_id=True
        )
    except TelegramDispatchMissingMessageId:
        logger.warning(
            "kapitalbank alerts: gateway answered OK without message_id; treated as sent tenant_id=%s",
            getattr(tenant, "pk", None),
        )
        return True
    except Exception:
        logger.exception("kapitalbank alerts: send failed tenant_id=%s", getattr(tenant, "pk", None))
        return False
    if message is None:
        logger.error("kapitalbank alerts: not delivered tenant_id=%s", getattr(tenant, "pk", None))
        return False
    return True


def send_owner_alert(
    text: str,
    *,
    tenant,
    link,
    kind: str,
    dedup_key: str | None = None,
    payload: dict | None = None,
) -> bool:
    recipient = KapitalbankAlertSettings.load().recipient
    chat_id = getattr(recipient, "telegram_chat_id", None) if recipient is not None else None
    if recipient is None or not chat_id:
        logger.error("kapitalbank alerts: alert settings incomplete (recipient / telegram chat id)")
        return False
    recipient_id = str(chat_id)

    event_payload = dict(payload or {})
    event_payload["recipient_id"] = recipient_id
    event_fields = {
        "tenant": tenant,
        "link": link,
        "kind": kind,
        "day": event_payload.get("day") and _parse_day(event_payload["day"]),
        "message": text,
        "payload": event_payload,
    }

    if dedup_key is None:
        if not _send_text(tenant=tenant, recipient_id=recipient_id, text=text):
            return False
        SyncEvent.objects.create(**event_fields)
        return True

    if SyncEvent.objects.filter(dedup_key=dedup_key).exists():
        return False
    try:
        with transaction.atomic():
            event = SyncEvent.objects.create(dedup_key=dedup_key, **event_fields)
    except IntegrityError:
        return False
    if _send_text(tenant=tenant, recipient_id=recipient_id, text=text):
        return True
    failed_payload = dict(event_payload, failed=True, failed_dedup_key=dedup_key)
    SyncEvent.objects.filter(pk=event.pk).update(dedup_key=None, payload=failed_payload)
    return False


def _parse_day(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _state(link: BankAccountLink) -> AccountSyncState:
    state, _ = AccountSyncState.objects.get_or_create(link=link)
    return state


def _due(alerted_at: datetime | None, now: datetime) -> bool:
    return alerted_at is None or now - alerted_at >= REPEAT_AFTER


def notify_mismatch(link: BankAccountLink, *, bank: Decimal, portal: Decimal, now: datetime) -> bool:
    state = _state(link)
    state.mismatch_bank = bank
    state.mismatch_portal = portal
    if state.mismatch_since is None:
        state.mismatch_since = now
    state.save(update_fields=["mismatch_bank", "mismatch_portal", "mismatch_since"])
    if not _due(state.mismatch_alerted_at, now):
        return False
    text = (
        "<b>Расхождение остатка Капиталбанк</b>\n"
        f"Организация: {_esc(link.tenant.name)}\n"
        f"Счёт: {_esc(_account_label(link))}\n"
        f"Банк: {_money(bank, link)}\n"
        f"Портал: {_money(portal, link)}\n"
        f"Разница: {_money(portal - bank, link)}\n"
        f"Сверка: {_fmt_time(now)}"
    )
    sent = send_owner_alert(
        text,
        tenant=link.tenant,
        link=link,
        kind=SyncEvent.ALERT_MISMATCH,
        payload={"bank": str(bank), "portal": str(portal)},
    )
    if sent:
        state.mismatch_alerted_at = now
        state.save(update_fields=["mismatch_alerted_at"])
    return sent


def notify_resolved(link: BankAccountLink, *, now: datetime) -> bool:
    state = _state(link)
    if state.mismatch_since is None and state.mismatch_alerted_at is None:
        return False
    if state.mismatch_alerted_at is not None:
        text = (
            "<b>Остаток Капиталбанк сошёлся</b>\n"
            f"Организация: {_esc(link.tenant.name)}\n"
            f"Счёт: {_esc(_account_label(link))}\n"
            f"Сверка: {_fmt_time(now)}"
        )
        if not send_owner_alert(text, tenant=link.tenant, link=link, kind=SyncEvent.ALERT_RESOLVED):
            # Keep the mismatch state: the next matching run retries the message.
            return False
        sent = True
    else:
        sent = False  # the mismatch was never alerted: nothing to tell the owner
    state.mismatch_bank = None
    state.mismatch_portal = None
    state.mismatch_since = None
    state.mismatch_alerted_at = None
    state.save(update_fields=["mismatch_bank", "mismatch_portal", "mismatch_since", "mismatch_alerted_at"])
    return sent


def notify_down(link: BankAccountLink, *, code: int | None, message: str, now: datetime) -> bool:
    state = _state(link)
    if not _due(state.down_alerted_at, now):
        return False
    text = (
        "<b>Загрузка выписок Капиталбанк не работает</b>\n"
        f"Организация: {_esc(link.tenant.name)}\n"
        f"Счёт: {_esc(_account_label(link))}\n"
        f"Код: {_esc(code if code is not None else '—')}\n"
        f"Ответ банка: {_esc(message)}\n"
        f"Время: {_fmt_time(now)}"
    )
    sent = send_owner_alert(
        text,
        tenant=link.tenant,
        link=link,
        kind=SyncEvent.ALERT_DOWN,
        payload={"code": code},
    )
    if sent:
        state.down_alerted_at = now
        state.save(update_fields=["down_alerted_at"])
    return sent


def notify_own_transfer(link: BankAccountLink, doc: StatementDoc, *, target_account: str) -> bool:
    target = BankAccountLink.objects.filter(tenant=link.tenant, account_no=target_account).first()
    if target is not None and target.decision == BankAccountLink.PENDING:
        note = "счёт не разобран"
    else:
        note = "счёт не отслеживается"
    text = (
        "<b>Перевод на свой счёт</b>\n"
        f"Организация: {_esc(link.tenant.name)}\n"
        f"Со счёта: {_esc(_account_label(link))}\n"
        f"Сумма: {_money(doc.amount, link)}\n"
        f"Дата: {doc.ddate.strftime('%d.%m.%Y')}\n"
        f"Счёт получателя: {_esc(target_account)} ({note})\n"
        f"Назначение: {_esc(doc.purpose)}"
    )
    return send_owner_alert(
        text,
        tenant=link.tenant,
        link=link,
        kind=SyncEvent.ALERT_OWN_TRANSFER,
        dedup_key=f"own_transfer:{link.pk}:{doc.general_id}",
        payload={"general_id": doc.general_id, "target_account": target_account},
    )


def notify_missing_docs(link: BankAccountLink, *, day: date, external_ids: list[str], now: datetime) -> bool:
    ids = ", ".join(_esc(i) for i in external_ids[:20])
    more = f" и ещё {len(external_ids) - 20}" if len(external_ids) > 20 else ""
    text = (
        "<b>Документы пропали после загрузки</b>\n"
        f"Организация: {_esc(link.tenant.name)}\n"
        f"Счёт: {_esc(_account_label(link))}\n"
        f"День: {day.strftime('%d.%m.%Y')}\n"
        f"Документов: {len(external_ids)}\n"
        f"ID: {ids}{more}"
    )
    return send_owner_alert(
        text,
        tenant=link.tenant,
        link=link,
        kind=SyncEvent.MISSING_DOCS,
        dedup_key=f"missing:{link.pk}:{day.isoformat()}:{timezone.localtime(now).date().isoformat()}",
        payload={"day": day.isoformat(), "external_ids": list(external_ids)},
    )


def notify_accounts_refresh_failed(tenant, *, message: str, today: date, now: datetime) -> bool:
    """Nightly account-list refresh failed; at most once per tenant and local day.
    ``message`` must already be redacted by the caller."""
    text = (
        "<b>Список счетов Капиталбанк не обновился</b>\n"
        f"Организация: {_esc(tenant.name)}\n"
        f"Ошибка: {_esc(message)}\n"
        f"Время: {_fmt_time(now)}"
    )
    return send_owner_alert(
        text,
        tenant=tenant,
        link=None,
        kind=SyncEvent.ALERT_DOWN,
        dedup_key=f"accounts_refresh:{tenant.pk}:{today.isoformat()}",
        payload={"stage": "account_list"},
    )
