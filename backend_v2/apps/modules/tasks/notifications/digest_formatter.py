"""Formats the daily task digest message for Telegram (HTML parse mode)."""

from __future__ import annotations

from html import escape
from typing import Any


def _task_line(task: Any) -> str:
    title = escape(str(task.title or ""))
    if task.source_request_id:
        return f"• {title} (заявка #{task.source_request_id})"
    return f"• {title}"


def format_digest(*, user: Any, dashboard: dict) -> str:
    new_tasks: list = dashboard.get("new") or []
    in_progress_tasks: list = dashboard.get("in_progress") or []
    done_tasks: list = dashboard.get("done_recent") or []

    # Prefer the user's full name; fall back to username if not set or unsupported.
    full_name_getter = getattr(user, "get_full_name", None)
    full_name = full_name_getter() if callable(full_name_getter) else ""
    display_name = escape(str((full_name or "").strip() or user.username))

    lines: list[str] = [f"☀ <b>Доброе утро, {display_name}!</b>", ""]

    if new_tasks:
        lines.append(f"📋 <b>НОВЫЕ ({len(new_tasks)}):</b>")
        for t in new_tasks:
            lines.append(f"  {_task_line(t)}")
        lines.append("")

    if in_progress_tasks:
        lines.append(f"🔧 <b>В РАБОТЕ ({len(in_progress_tasks)}):</b>")
        for t in in_progress_tasks:
            lines.append(f"  {_task_line(t)}")
        lines.append("")

    if done_tasks:
        lines.append(f"✅ <b>ВЫПОЛНЕНО (последние {len(done_tasks)}):</b>")
        for t in done_tasks:
            lines.append(f"  {_task_line(t)}")
        lines.append("")

    if not new_tasks and not in_progress_tasks:
        lines.append("У вас нет активных задач. Отличная работа!")

    return "\n".join(lines).strip()


def digest_buttons(*, tasks_webapp_url: str) -> list:
    """Return button rows for the digest message. Empty list if no URL configured."""
    url = (tasks_webapp_url or "").strip()
    if not url:
        return []
    return [[{"label": "Открыть задачи", "url": url}]]
