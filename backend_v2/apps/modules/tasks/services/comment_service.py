from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.modules.tasks.models import Task, TaskComment
from apps.modules.tasks.permissions import _is_tenant_admin_or_director


def add_comment(*, task: Task, author, body: str) -> TaskComment:
    body = body.strip()
    if not body:
        raise ValidationError("Comment body must not be empty.")

    with transaction.atomic():
        comment = TaskComment.objects.create(
            task=task,
            author=author,
            body=body,
        )
        _update_admin_comment_badge(task=task, author=author)

    return comment


def _update_admin_comment_badge(*, task: Task, author) -> None:
    """Set last_admin_comment_at when a director/admin comments on another user's task."""
    if author.id == task.assignee_id:
        return

    tenant = task.tenant
    if not _is_tenant_admin_or_director(author, tenant):
        return

    task.last_admin_comment_at = timezone.now()
    task.save(update_fields=["last_admin_comment_at"])
