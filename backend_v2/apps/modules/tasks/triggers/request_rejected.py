from __future__ import annotations

import logging

from apps.modules.tasks.triggers.base import AbstractTaskTrigger
from apps.modules.tasks.triggers.registry import task_trigger_registry

logger = logging.getLogger(__name__)


class RequestRejectedTrigger(AbstractTaskTrigger):
    """Handles request rejection (plan §5.5):

    1. Closes all open tasks linked to the rejected request — the approver who
       decided already had their task closed by ApprovalStepDecidedTrigger; this
       catches co-approvers at the same step whose approvals were bulk-canceled.
    2. Creates a "Notify and revise" task for the requester, so they know the
       request was rejected and can decide next steps.
    """

    event_name = "request_rejected"

    def handle(self, *, request_obj, **context) -> None:
        from apps.modules.tasks.models import Task
        from apps.modules.tasks.services import task_service

        closed = task_service.close_all_open_tasks_for_request(request_obj=request_obj)
        if closed:
            logger.debug(
                "RequestRejectedTrigger: closed %d open task(s) for request %s.",
                closed,
                request_obj.pk,
            )

        requester = getattr(request_obj, "requester", None)
        if requester is None:
            logger.debug(
                "RequestRejectedTrigger: request %s has no requester, skipping notify task.",
                request_obj.pk,
            )
            return

        # Idempotency: don't create a second notify task if one already exists.
        if Task.objects.filter(
            source_type=Task.SOURCE_REQUEST_REJECTED,
            source_request=request_obj,
            status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
        ).exists():
            logger.debug(
                "RequestRejectedTrigger: open notify task already exists for request %s, skipping.",
                request_obj.pk,
            )
            return

        task_service.create_task(
            tenant=request_obj.tenant,
            assignee=requester,
            title=f"Заявка #{request_obj.pk} отклонена — проверьте и решите дальнейшие шаги",
            description=request_obj.title or "",
            created_by=None,
            source_type=Task.SOURCE_REQUEST_REJECTED,
            source_approval=None,
            source_request=request_obj,
            source_expense_type="",
            source_expense_id=None,
        )


task_trigger_registry.register(RequestRejectedTrigger())
