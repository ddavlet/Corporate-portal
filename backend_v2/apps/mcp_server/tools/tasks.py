"""MCP tools for the Tasks module."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe

MODULE = "tasks"
_MAX_LIMIT = 200


def _task_to_dict(t) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "source_type": t.source_type,
        "assignee_id": t.assignee_id,
        "created_by_id": t.created_by_id,
        "source_request_id": t.source_request_id,
        "source_approval_id": t.source_approval_id,
        "source_expense_type": t.source_expense_type,
        "source_expense_id": t.source_expense_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


def list_tasks(
    tenant_id: int,
    status: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return tasks visible to the current user, with optional status filter.

    Admins and directors see all tenant tasks; everyone else sees only
    their own assigned tasks (mirrors the web UI scope rules).
    """
    user, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.tasks.models import Task
    from apps.modules.tasks.querysets.resolver import resolve_scope_for_user

    scope = resolve_scope_for_user(user, tenant)
    qs = scope.filter_queryset(
        Task.objects.filter(tenant=tenant).select_related("assignee"),
        user,
        tenant,
    )

    if status:
        qs = qs.filter(status=status)

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return [_task_to_dict(t) for t in qs.order_by("-created_at")[:limit]]


def get_task_detail(tenant_id: int, task_id: int) -> dict[str, Any]:
    """Return a single task (with comments) if the user has access to it."""
    user, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.tasks.models import Task
    from apps.modules.tasks.querysets.resolver import resolve_scope_for_user

    scope = resolve_scope_for_user(user, tenant)
    qs = scope.filter_queryset(
        Task.objects.filter(tenant=tenant).prefetch_related("comments__author"),
        user,
        tenant,
    )

    try:
        task = qs.get(id=task_id)
    except Task.DoesNotExist:
        raise ValueError(f"Task {task_id} not found or not accessible")

    data = _task_to_dict(task)
    data["description"] = task.description
    data["comments"] = json_safe([
        {
            "id": c.id,
            "author_id": c.author_id,
            "body": c.body,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in task.comments.all().order_by("created_at")
    ])
    return data
