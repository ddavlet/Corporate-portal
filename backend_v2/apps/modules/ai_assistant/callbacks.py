"""Кнопки «Подтвердить»/«Отменить» под предложением изменений от ассистента."""

import logging

from django.db import transaction
from django.utils import timezone

from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.models import TelegramMessageHistory
from apps.modules.telegram_approvals.services import TelegramDispatcher

from .config import CALLBACK_PREFIX
from .jobs import submit_resume
from .models import PendingConfirmation

logger = logging.getLogger(__name__)

EXPIRED_TEXT = "Запрос устарел."
STATUS_LINES = {
    PendingConfirmation.STATUS_CONFIRMED: "✅ Подтверждено",
    PendingConfirmation.STATUS_CANCELLED: "❌ Отменено",
}
DECISIONS = {"y": ("confirm", PendingConfirmation.STATUS_CONFIRMED), "n": ("cancel", PendingConfirmation.STATUS_CANCELLED)}


def _ignored(code: int = 200) -> tuple[int, dict]:
    return code, {"detail": "ignored"}


def _int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse(payload: str):
    if not payload.startswith(CALLBACK_PREFIX):
        return None
    parts = payload[len(CALLBACK_PREFIX):].split(":")
    if len(parts) != 2 or parts[1] not in DECISIONS:
        return None
    pending_id = _int_or_none(parts[0])
    if pending_id is None:
        return None
    return pending_id, parts[1]


def _current_text(message) -> str:
    row = (
        TelegramMessageHistory.objects.filter(telegram_message=message, success=True)
        .exclude(text="")
        .order_by("-created_at", "-id")
        .first()
    )
    return row.text if row else ""


def _edit_message(tenant, pending, text: str) -> None:
    """Снять кнопки и обновить текст; сбой правки только логируется."""
    message = pending.confirmation_message
    try:
        result = TelegramDispatcher(tenant).deactivate(
            message,
            action=get_requests_messaging_gateway_settings(tenant=tenant).edit_action,
            text=text,
        )
        if result is None:
            logger.warning("ai_assistant: confirmation edit failed pending_id=%s", pending.pk)
    except Exception:
        logger.exception("ai_assistant: confirmation edit raised pending_id=%s", pending.pk)


def handle_confirmation_callback(*, payload: str, event_data: dict) -> tuple[int, dict]:
    parsed = _parse(payload)
    if parsed is None:
        logger.info("ai_assistant: bad confirmation payload %r", payload[:48])
        return _ignored(202)
    pending_id, choice = parsed

    chat_id = str(event_data.get("recipient_id") or "").strip()
    presser = _int_or_none(event_data.get("user_id"))
    message_id = _int_or_none(event_data.get("message_id"))
    pending = (
        PendingConfirmation.objects.select_related("tenant", "confirmation_message")
        .filter(
            pk=pending_id,
            chat_id=chat_id,
            confirmation_message__message_id=message_id,
        )
        .first()
        if message_id is not None
        else None
    )
    if pending is None:
        logger.info("ai_assistant: confirmation %s not found for this chat/message", pending_id)
        return _ignored()
    tenant = pending.tenant
    if presser is None or presser != pending.requester_tg_id:
        logger.info("ai_assistant: confirmation %s pressed by non-requester %s", pending_id, presser)
        return _ignored()

    now = timezone.now()
    with transaction.atomic():
        if now > pending.expires_at:
            expired = PendingConfirmation.objects.filter(
                pk=pending.pk, status=PendingConfirmation.STATUS_PENDING
            ).update(status=PendingConfirmation.STATUS_EXPIRED, resolved_at=now)
            outcome = "expired" if expired else None
        else:
            decision, new_status = DECISIONS[choice]
            changed = PendingConfirmation.objects.filter(
                pk=pending.pk, status=PendingConfirmation.STATUS_PENDING
            ).update(status=new_status, resolved_at=now)
            outcome = new_status if changed else None
            if changed:
                submit_resume(pending.pk, decision)

    if outcome is None:
        return _ignored()
    if outcome == "expired":
        _edit_message(tenant, pending, EXPIRED_TEXT)
        return 200, {"detail": "expired"}

    base = _current_text(pending.confirmation_message)
    status_line = STATUS_LINES[outcome]
    _edit_message(tenant, pending, f"{base}\n\n{status_line}" if base else status_line)
    return 200, {"detail": outcome}
