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
        "assignee_id": t.assignee_id,
        "created_by_id": t.created_by_id,
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


def _require_admin_or_director(user, tenant) -> None:
    from apps.modules.tasks.permissions import _is_tenant_admin_or_director
    if not _is_tenant_admin_or_director(user, tenant):
        raise PermissionError("Только admin или director могут выполнять это действие.")


def _require_task_access(user, tenant, task) -> None:
    """Raise PermissionError if user cannot act on this task."""
    from apps.modules.tasks.permissions import _is_tenant_admin_or_director
    if task.assignee_id == user.id:
        return
    if task.tenant_id != tenant.id:
        raise PermissionError("Задача не принадлежит этому тенанту.")
    if not _is_tenant_admin_or_director(user, tenant):
        raise PermissionError("Доступ запрещён: вы не являетесь исполнителем задачи.")


def create_task(
    tenant_id: int,
    assignee_id: int,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    """Create a manual task and assign it to a tenant member.

    Only admins and directors can assign tasks to other users.
    Regular users may only create tasks for themselves — use the web UI for that.

    Args:
        tenant_id: Tenant primary key.
        assignee_id: User ID of the person who will own the task.
        title: Task title (max 255 chars).
        description: Optional detailed description.
    """
    user, tenant = require_module_access(tenant_id, MODULE)
    _require_admin_or_director(user, tenant)

    from django.contrib.auth import get_user_model
    from apps.tenants.models import TenantMembership
    from apps.modules.tasks.models import Task
    from apps.modules.tasks.services import task_service

    User = get_user_model()
    if not TenantMembership.objects.filter(tenant=tenant, user_id=assignee_id, is_active=True).exists():
        raise ValueError(f"Пользователь {assignee_id} не является активным участником тенанта.")

    assignee = User.objects.get(pk=assignee_id)
    task = task_service.create_task(
        tenant=tenant,
        assignee=assignee,
        title=title.strip(),
        description=description.strip(),
        created_by=user,
    )
    return json_safe(_task_to_dict(task))


def update_task_status(
    tenant_id: int,
    task_id: int,
    new_status: str,
) -> dict[str, Any]:
    """Change the status of a task.

    Allowed transitions:
      new → in_progress | done
      in_progress → new | done
      done → (no transitions allowed)

    Admins and directors can change status of any task in the tenant.
    Other roles can only change status of tasks assigned to themselves.

    Args:
        tenant_id: Tenant primary key.
        task_id: Task primary key.
        new_status: One of: new, in_progress, done.
    """
    user, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.tasks.models import Task
    from apps.modules.tasks.services import task_service
    from apps.modules.tasks.querysets.resolver import resolve_scope_for_user

    scope = resolve_scope_for_user(user, tenant)
    qs = scope.filter_queryset(Task.objects.filter(tenant=tenant), user, tenant)
    try:
        task = qs.get(id=task_id)
    except Task.DoesNotExist:
        raise ValueError(f"Задача {task_id} не найдена или недоступна.")

    _require_task_access(user, tenant, task)

    from django.core.exceptions import ValidationError as DjangoValidationError
    try:
        updated = task_service.set_status(task=task, new_status=new_status, actor=user)
    except DjangoValidationError as e:
        raise ValueError(str(e))
    return json_safe(_task_to_dict(updated))


def add_task_comment(
    tenant_id: int,
    task_id: int,
    body: str,
) -> dict[str, Any]:
    """Post a comment on a task.

    Admins and directors can comment on any task in the tenant (their comments
    appear with an admin badge visible to the assignee).
    Other roles can only comment on their own tasks.

    Args:
        tenant_id: Tenant primary key.
        task_id: Task primary key.
        body: Comment text (must not be empty).
    """
    user, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.tasks.models import Task
    from apps.modules.tasks.querysets.resolver import resolve_scope_for_user
    from apps.modules.tasks.services import comment_service

    scope = resolve_scope_for_user(user, tenant)
    qs = scope.filter_queryset(Task.objects.filter(tenant=tenant), user, tenant)
    try:
        task = qs.get(id=task_id)
    except Task.DoesNotExist:
        raise ValueError(f"Задача {task_id} не найдена или недоступна.")

    _require_task_access(user, tenant, task)

    from django.core.exceptions import ValidationError as DjangoValidationError
    try:
        comment = comment_service.add_comment(task=task, author=user, body=body)
    except DjangoValidationError as e:
        raise ValueError(str(e))
    return json_safe({
        "id": comment.id,
        "task_id": comment.task_id,
        "author_id": comment.author_id,
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    })


def _require_can_edit_or_delete(user, tenant, task) -> None:
    """Raise PermissionError if user is neither the creator nor admin/director."""
    from apps.modules.tasks.permissions import _is_tenant_admin_or_director
    if task.created_by_id == user.id:
        return
    if task.tenant_id != tenant.id or not _is_tenant_admin_or_director(user, tenant):
        raise PermissionError("Только создатель задачи, admin или director могут выполнить это действие.")


def edit_task(
    tenant_id: int,
    task_id: int,
    title: str = "",
    description: str = "",
    assignee_id: int = 0,
) -> dict[str, Any]:
    """Update a task's title, description, or assignee.

    Only the task creator, admin, or director can edit a task.
    Pass only the fields you want to change — omitted fields are left unchanged.
    Reassigning to a different user requires admin or director role.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        task_id: Task primary key (get from list_my_tasks).
        title: New title (leave empty to keep current).
        description: New description (leave empty to keep current).
        assignee_id: New assignee user ID (0 = keep current).
    """
    user, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.tasks.models import Task
    from apps.modules.tasks.querysets.resolver import resolve_scope_for_user
    from apps.modules.tasks.permissions import _is_tenant_admin_or_director

    scope = resolve_scope_for_user(user, tenant)
    qs = scope.filter_queryset(Task.objects.filter(tenant=tenant), user, tenant)
    try:
        task = qs.get(id=task_id)
    except Task.DoesNotExist:
        raise ValueError(f"Задача {task_id} не найдена или недоступна.")

    _require_can_edit_or_delete(user, tenant, task)

    update_fields: list[str] = []
    if title and title.strip() != task.title:
        task.title = title.strip()
        update_fields.append("title")
    if description != "" and description != task.description:
        task.description = description
        update_fields.append("description")
    if assignee_id and assignee_id != task.assignee_id:
        if not _is_tenant_admin_or_director(user, tenant):
            raise PermissionError("Только admin или director могут переназначить задачу.")
        from apps.tenants.models import TenantMembership
        if not TenantMembership.objects.filter(tenant=tenant, user_id=assignee_id, is_active=True).exists():
            raise ValueError(f"Пользователь {assignee_id} не является активным участником тенанта.")
        task.assignee_id = assignee_id
        update_fields.append("assignee_id")

    if update_fields:
        update_fields.append("updated_at")
        task.save(update_fields=update_fields)
        task.refresh_from_db()

    return json_safe(_task_to_dict(task))


def delete_task(tenant_id: int, task_id: int) -> dict[str, Any]:
    """Delete a task permanently.

    Only the task creator, admin, or director can delete a task.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        task_id: Task primary key (get from list_my_tasks).
    """
    user, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.tasks.models import Task
    from apps.modules.tasks.querysets.resolver import resolve_scope_for_user

    scope = resolve_scope_for_user(user, tenant)
    qs = scope.filter_queryset(Task.objects.filter(tenant=tenant), user, tenant)
    try:
        task = qs.get(id=task_id)
    except Task.DoesNotExist:
        raise ValueError(f"Задача {task_id} не найдена или недоступна.")

    _require_can_edit_or_delete(user, tenant, task)
    task_id_deleted = task.id
    task.delete()
    return {"deleted": True, "task_id": task_id_deleted}


def list_assignee_candidates(tenant_id: int) -> list[dict[str, Any]]:
    """List users who can be assigned a task in this tenant.

    Admins and directors see all active members.
    All other roles see only themselves (they may only self-assign).

    Use this before create_task or edit_task to find valid assignee_id values.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
    """
    user, tenant = require_module_access(tenant_id, MODULE)

    from apps.modules.tasks.permissions import _is_tenant_admin_or_director
    from apps.tenants.models import TenantMembership

    if _is_tenant_admin_or_director(user, tenant):
        memberships = (
            TenantMembership.objects.filter(tenant=tenant, is_active=True)
            .select_related("user")
            .order_by("user__full_name")
        )
        return json_safe([
            {"id": m.user_id, "full_name": m.user.get_full_name() or m.user.username, "username": m.user.username}
            for m in memberships
        ])
    else:
        return json_safe([
            {"id": user.id, "full_name": user.get_full_name() or user.username, "username": user.username}
        ])
