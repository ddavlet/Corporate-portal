from __future__ import annotations

import logging

from apps.modules.tasks.triggers.base import AbstractTaskTrigger
from apps.modules.tasks.triggers.registry import task_trigger_registry

logger = logging.getLogger(__name__)


class ApprovalStepDecidedTrigger(AbstractTaskTrigger):
    """Closes the approver's task when they submit a decision."""

    event_name = "approval_step_decided"

    def handle(self, *, approval, request_obj, **context) -> None:
        from apps.modules.tasks.services import task_service

        task_service.close_task_for_approval(approval=approval)


task_trigger_registry.register(ApprovalStepDecidedTrigger())
