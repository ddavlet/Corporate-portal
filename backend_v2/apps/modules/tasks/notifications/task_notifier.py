"""Telegram notifications for individual tasks (creation and reminders)."""

from __future__ import annotations

import logging
from html import escape
from typing import Any

logger = logging.getLogger(__name__)

_CB_PROGRESS = "task_p_{}"
_CB_DONE = "task_a_{}"


def _task_buttons(task_id: int, current_status: str) -> list:
    if current_status == "new":
        return [[
            {"label": "▶ Взять в работу", "callback_data": _CB_PROGRESS.format(task_id)},
            {"label": "✅ Выполнено", "callback_data": _CB_DONE.format(task_id)},
        ]]
    if current_status == "in_progress":
        return [[
            {"label": "✅ Выполнено", "callback_data": _CB_DONE.format(task_id)},
        ]]
    return []


def _webapp_button(tenant: Any) -> list:
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


def send_task_notification(
    *,
    task: Any,
    tenant: Any,
    bot_token: str,
    is_reminder: bool = False,
) -> None:
    """Send a Telegram notification for a task (new assignment or reminder)."""
    from apps.modules.telegram_approvals.services import post_messaging_gateway

    recipient_id = getattr(task.assignee, "telegram_from_id", None)
    if not recipient_id:
        logger.info("send_task_notification: assignee has no telegram_from_id task_id=%s", task.pk)
        return

    prefix = "⏰ <b>Напоминание о задаче</b>\n\n" if is_reminder else "📋 <b>Вам назначена новая задача</b>\n\n"
    payload = {
        "action": "send",
        "text": _format_message(task, prefix),
        "recipient_id": str(recipient_id),
        "bot_token": bot_token,
        "tenant_id": str(tenant.pk),
        "buttons": _task_buttons(task.id, task.status) + _webapp_button(tenant),
    }
    post_messaging_gateway(tenant=tenant, payload=payload)
