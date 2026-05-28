from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.modules.tasks.models import Task

logger = logging.getLogger(__name__)

# Valid one-way status transitions.
# OCP: extend the set for a status to allow new paths; never edit transition logic.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Task.Status.NEW: {Task.Status.IN_PROGRESS, Task.Status.DONE},
    Task.Status.IN_PROGRESS: {Task.Status.NEW, Task.Status.DONE},
    Task.Status.DONE: set(),
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
    created_by,
) -> Task:
    now = timezone.now()
    with transaction.atomic():
        return Task.objects.create(
            tenant=tenant,
            assignee=assignee,
            title=title,
            description=description,
            created_by=created_by,
            status=Task.Status.NEW,
            last_edit_at=now,
            last_edit_by=created_by,
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
        if new_status == Task.Status.DONE:
            locked.completed_at = timezone.now()
            update_fields.append("completed_at")
        if actor is not None:
            locked.last_edit_at = timezone.now()
            locked.last_edit_by = actor
            update_fields += ["last_edit_at", "last_edit_by"]
        locked.save(update_fields=update_fields)
    return locked


def get_user_dashboard(user, tenant, include_all_done: bool = False) -> dict:
    """Return task counts/lists for the Telegram digest and the dashboard endpoint."""
    base_qs = (
        Task.objects
        .filter(tenant=tenant, assignee=user)
        .select_related("assignee")
    )

    new_tasks = list(base_qs.filter(status=Task.Status.NEW))
    in_progress_tasks = list(base_qs.filter(status=Task.Status.IN_PROGRESS))

    done_qs = base_qs.filter(status=Task.Status.DONE).order_by("-completed_at")
    if not include_all_done:
        done_qs = done_qs[:3]

    return {
        "new": new_tasks,
        "in_progress": in_progress_tasks,
        "done_recent": list(done_qs),
    }
