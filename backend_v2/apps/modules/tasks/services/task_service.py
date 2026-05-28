from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.modules.requests.models import Request
from apps.modules.tasks.models import Task
from apps.tenants.models import TenantUserRole

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCP extension point: map payment_type -> role that owns the task.
# Adding a new payment type = one new entry here, nowhere else.
# ---------------------------------------------------------------------------
_PAYMENT_TYPE_TO_ROLE: dict[str, str] = {
    Request.PAYMENT_TYPE_CASH: TenantUserRole.ROLE_CASHIER,
    Request.PAYMENT_TYPE_TRANSFER: TenantUserRole.ROLE_ACCOUNTANT,
    Request.PAYMENT_TYPE_TOPUP: TenantUserRole.ROLE_ACCOUNTANT,
    Request.PAYMENT_TYPE_CARD: TenantUserRole.ROLE_ACCOUNTANT,
}

# Valid one-way status transitions.
# OCP: extend the set for a status to allow new paths; never edit transition logic.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Task.STATUS_NEW: {Task.STATUS_IN_PROGRESS, Task.STATUS_DONE},
    Task.STATUS_IN_PROGRESS: {Task.STATUS_NEW, Task.STATUS_DONE},
    Task.STATUS_DONE: set(),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_task(
    *,
    tenant,
    assignee,
    title: str,
    description: str = "",
    created_by=None,
    source_type: str = Task.SOURCE_MANUAL,
    source_approval=None,
    source_request=None,
    source_expense_type: str = "",
    source_expense_id: int | None = None,
) -> Task:
    with transaction.atomic():
        return Task.objects.create(
            tenant=tenant,
            assignee=assignee,
            title=title,
            description=description,
            created_by=created_by,
            status=Task.STATUS_NEW,
            source_type=source_type,
            source_approval=source_approval,
            source_request=source_request,
            source_expense_type=source_expense_type or "",
            source_expense_id=source_expense_id,
        )


def set_status(*, task: Task, new_status: str, actor) -> Task:
    """Move a task to a new status. Concurrent-safe via row-level lock.

    Two writers racing on the same task (e.g. drag-and-drop + status button) cannot
    both pass the transition check: select_for_update serializes them, and we
    re-read + re-validate after acquiring the lock.

    When actor is not None (human-initiated change), last_edit_at / last_edit_by
    are stamped in the same save. actor=None means a system/trigger change — not tracked.
    """
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        allowed = _ALLOWED_TRANSITIONS.get(locked.status, set())
        if new_status not in allowed:
            raise ValidationError(
                f"Cannot transition task from '{locked.status}' to '{new_status}'."
            )
        locked.status = new_status
        update_fields = ["status", "updated_at"]
        if new_status == Task.STATUS_DONE:
            locked.completed_at = timezone.now()
            update_fields.append("completed_at")
        if actor is not None:
            locked.last_edit_at = timezone.now()
            locked.last_edit_by = actor
            update_fields += ["last_edit_at", "last_edit_by"]
        locked.save(update_fields=update_fields)
    return locked


def close_task_for_approval(*, approval) -> Task | None:
    """Close the open task linked to an Approval row. Idempotent."""
    task = Task.objects.filter(
        source_approval=approval,
        status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
    ).first()
    if task is None:
        return None
    return set_status(task=task, new_status=Task.STATUS_DONE, actor=None)


def close_all_open_tasks_for_request(*, request_obj) -> int:
    """Close every open task linked to a request. Returns the count closed.

    Used on rejection: any co-approver tasks at the same step (bulk-canceled
    by the approval workflow) must also be closed so assignees stop seeing them.
    """
    open_tasks = list(
        Task.objects.filter(
            source_request=request_obj,
            status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
        )
    )
    for task in open_tasks:
        set_status(task=task, new_status=Task.STATUS_DONE, actor=None)
    return len(open_tasks)


def close_task_for_request_payment(*, request_obj) -> Task | None:
    """Close the 'Process payment' task linked to a Request. Idempotent."""
    task = Task.objects.filter(
        source_type=Task.SOURCE_REQUEST_APPROVED,
        source_request=request_obj,
        status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
    ).first()
    if task is None:
        return None
    return set_status(task=task, new_status=Task.STATUS_DONE, actor=None)


def mark_task_seen(*, task: Task, user) -> None:
    """Clear the unread admin-comment badge for the assignee."""
    if task.assignee_id != user.id:
        return
    task.last_seen_at = timezone.now()
    task.save(update_fields=["last_seen_at"])


def assignee_for_payment(request_obj) -> object | None:
    """Resolve the user who should receive payment/verify tasks.

    OCP: the mapping lives in _PAYMENT_TYPE_TO_ROLE above.
    No if/elif chains here.
    """
    role = _PAYMENT_TYPE_TO_ROLE.get(request_obj.payment_type)
    if not role:
        logger.warning(
            "assignee_for_payment: unknown payment_type '%s' for request %s",
            request_obj.payment_type,
            request_obj.id,
        )
        return None

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = (
        User.objects.filter(
            tenant_roles__tenant=request_obj.tenant,
            tenant_roles__role=role,
        )
        .distinct()
        .order_by("username")
        .first()
    )
    if user is None:
        logger.warning(
            "assignee_for_payment: no user with role '%s' in tenant %s for request %s",
            role,
            request_obj.tenant_id,
            request_obj.id,
        )
    return user


def get_user_dashboard(user, tenant, include_all_done: bool = False) -> dict:
    """Return task counts/lists for the Telegram digest and the dashboard endpoint."""
    base_qs = (
        Task.objects
        .filter(tenant=tenant, assignee=user)
        .select_related("assignee", "source_request")
    )

    new_tasks = list(base_qs.filter(status=Task.STATUS_NEW))
    in_progress_tasks = list(base_qs.filter(status=Task.STATUS_IN_PROGRESS))

    done_qs = base_qs.filter(status=Task.STATUS_DONE).order_by("-completed_at")
    if not include_all_done:
        done_qs = done_qs[:3]

    return {
        "new": new_tasks,
        "in_progress": in_progress_tasks,
        "done_recent": list(done_qs),
    }
