"""Telegram notifications for individual tasks (creation, status change, reminders)."""

from __future__ import annotations

import logging
from html import escape
from typing import Any

logger = logging.getLogger(__name__)

# Callback data format: "task_<action>_<task_id>"
# task_p_<id>  → move to in_progress
# task_a_<id>  → archive (move to done)
_CB_PROGRESS = "task_p_{}"
_CB_ARCHIVE = "task_a_{}"


def _task_buttons(task_id: int, current_status: str) -> list:
    """Return inline button rows based on the current task status."""
    if current_status == "new":
        return [[
            {"label": "▶ Взять в работу", "callback_data": _CB_PROGRESS.format(task_id)},
            {"label": "✅ Архивировать", "callback_data": _CB_ARCHIVE.format(task_id)},
        ]]
    if current_status == "in_progress":
        return [[
            {"label": "✅ Выполнено", "callback_data": _CB_ARCHIVE.format(task_id)},
            {"label": "📦 Архивировать", "callback_data": _CB_ARCHIVE.format(task_id)},
        ]]
    return []


def _webapp_button(tenant: Any) -> list:
    """Return a webapp URL button row if configured for the tenant, else empty list."""
    try:
        from apps.modules.tasks.models import TasksConfig
        cfg = TasksConfig.objects.filter(tenant=tenant).first()
        url = (cfg.tasks_webapp_url if cfg else "") or ""
        if url.strip():
            return [[{"label": "📱 Открыть задачи", "url": url.strip()}]]
    except Exception:
        pass
    return []


def _format_message(task: Any, prefix: str) -> str:
    title = escape(str(task.title or ""))
    desc = escape(str(task.description or "")).strip()
    text = f"{prefix}<b>{title}</b>"
    if desc:
        text += f"\n{desc}"
    return text


def _extract_message_id(response: dict | None) -> int | None:
    if not isinstance(response, dict):
        return None
    raw = response.get("message_id")
    if raw is None:
        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        raw = result.get("message_id")  # type: ignore[union-attr]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def send_task_notification(
    *,
    task: Any,
    tenant: Any,
    bot_token: str,
    is_reminder: bool = False,
) -> int | None:
    """Send a Telegram notification for a task. Returns gateway message_id or None.

    Stores tg_notify_message_id / tg_notify_recipient_id on the task so
    subsequent status-change callbacks can edit the same message.
    """
    from apps.modules.telegram_approvals.services import post_messaging_gateway
    from apps.modules.tasks.models import Task

    recipient_id = getattr(task.assignee, "telegram_from_id", None)
    if not recipient_id:
        logger.info("send_task_notification: assignee has no telegram_from_id task_id=%s", task.pk)
        return None

    if is_reminder:
        prefix = "⏰ <b>Напоминание о задаче</b>\n\n"
    else:
        prefix = "📋 <b>Вам назначена новая задача</b>\n\n"

    message_text = _format_message(task, prefix)
    buttons = _task_buttons(task.id, task.status) + _webapp_button(tenant)

    payload = {
        "action": "send",
        "text": message_text,
        "recipient_id": str(recipient_id),
        "bot_token": bot_token,
        "tenant_id": str(tenant.pk),
        "buttons": buttons,
    }

    response = post_messaging_gateway(tenant=tenant, payload=payload)
    message_id = _extract_message_id(response)

    if message_id:
        Task.objects.filter(pk=task.pk).update(
            tg_notify_message_id=message_id,
            tg_notify_recipient_id=recipient_id,
        )

    return message_id


def edit_task_notification(*, task: Any, tenant: Any, bot_token: str) -> bool:
    """Edit the existing Telegram notification message after a status change."""
    from apps.modules.telegram_approvals.services import post_messaging_gateway

    if not task.tg_notify_message_id or not task.tg_notify_recipient_id:
        return False

    if task.status == "in_progress":
        prefix = "📋 <b>Задача взята в работу</b>\n\n"
    elif task.status == "done":
        prefix = "✅ <b>Задача завершена</b>\n\n"
    else:
        prefix = "📋 <b>Задача обновлена</b>\n\n"

    message_text = _format_message(task, prefix)
    buttons = _task_buttons(task.id, task.status)

    payload = {
        "action": "edit",
        "text": message_text,
        "recipient_id": str(task.tg_notify_recipient_id),
        "bot_token": bot_token,
        "tenant_id": str(tenant.pk),
        "message_id": task.tg_notify_message_id,
        "buttons": buttons,
    }

    response = post_messaging_gateway(tenant=tenant, payload=payload)
    return response is not None
