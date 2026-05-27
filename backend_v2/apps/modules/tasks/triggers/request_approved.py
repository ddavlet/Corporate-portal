from __future__ import annotations

import logging

from apps.modules.tasks.triggers.base import AbstractTaskTrigger
from apps.modules.tasks.triggers.registry import task_trigger_registry

logger = logging.getLogger(__name__)


class RequestApprovedTrigger(AbstractTaskTrigger):
    """Creates a payment-processing task when a request reaches APPROVED status.

    The assignee is the cashier or accountant determined by the request's
    payment_type via task_service.assignee_for_payment.
    """

    event_name = "request_approved"

    def handle(self, *, request_obj, **context) -> None:
        from apps.modules.tasks.models import Task
        from apps.modules.tasks.services import task_service

        if Task.objects.filter(
            source_type=Task.SOURCE_REQUEST_APPROVED,
            source_request=request_obj,
            status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
        ).exists():
            logger.debug(
                "RequestApprovedTrigger: open task already exists for request %s, skipping.",
                request_obj.pk,
            )
            return

        assignee = task_service.assignee_for_payment(request_obj)
        if assignee is None:
            logger.warning(
                "RequestApprovedTrigger: no assignee found for request %s (payment_type=%s), skipping.",
                request_obj.pk,
                getattr(request_obj, "payment_type", None),
            )
            return

        task_service.create_task(
            tenant=request_obj.tenant,
            assignee=assignee,
            title=f"Провести оплату по заявке #{request_obj.pk}",
            description=request_obj.title or "",
            created_by=None,
            source_type=Task.SOURCE_REQUEST_APPROVED,
            source_approval=None,
            source_request=request_obj,
            source_expense_type="",
            source_expense_id=None,
        )


task_trigger_registry.register(RequestApprovedTrigger())
