from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.modules.tasks.models import Task, TaskComment


def add_comment(*, task: Task, author, body: str) -> TaskComment:
    body = body.strip()
    if not body:
        raise ValidationError("Comment body must not be empty.")

    with transaction.atomic():
        return TaskComment.objects.create(
            task=task,
            author=author,
            body=body,
        )
