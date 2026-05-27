from __future__ import annotations

import logging

from apps.modules.tasks.triggers.base import AbstractTaskTrigger
from apps.modules.tasks.triggers.registry import task_trigger_registry

logger = logging.getLogger(__name__)


class ApprovalStepActivatedTrigger(AbstractTaskTrigger):
    """Creates a task for the approver when their step becomes active."""

    event_name = "approval_step_activated"

    def handle(self, *, approval, request_obj, **context) -> None:
        from apps.modules.tasks.models import Task
        from apps.modules.tasks.services import task_service

        assignee = getattr(approval, "approver_user", None)
        if assignee is None:
            logger.debug(
                "ApprovalStepActivatedTrigger: approval %s has no approver_user, skipping.",
                approval.pk,
            )
            return

        if Task.objects.filter(
            source_approval=approval,
            status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
        ).exists():
            logger.debug(
                "ApprovalStepActivatedTrigger: open task already exists for approval %s, skipping.",
                approval.pk,
            )
            return

        task_service.create_task(
            tenant=request_obj.tenant,
            assignee=assignee,
            title=f"Согласовать заявку #{request_obj.pk}",
            description=request_obj.title or "",
            created_by=None,
            source_type=Task.SOURCE_APPROVAL_STEP,
            source_approval=approval,
            source_request=request_obj,
            source_expense_type="",
            source_expense_id=None,
        )


task_trigger_registry.register(ApprovalStepActivatedTrigger())
