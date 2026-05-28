from __future__ import annotations

import logging

from apps.modules.tasks.triggers.base import AbstractTaskTrigger
from apps.modules.tasks.triggers.registry import task_trigger_registry

logger = logging.getLogger(__name__)


class PaymentConfirmedTrigger(AbstractTaskTrigger):
    """Closes the payment-processing task and opens a verify-transaction task.

    Per the plan (§5.4):
      1. Close the open "Process payment" task linked to the request.
      2. Create a "Verify transaction" task. Defaults to the same user who
         processed the payment; falls back to the role-based resolution if the
         original assignee cannot be determined.
    """

    event_name = "payment_confirmed"

    def handle(self, *, request_obj, **context) -> None:
        from apps.modules.tasks.models import Task
        from apps.modules.tasks.services import task_service

        closed = task_service.close_task_for_request_payment(request_obj=request_obj)

        # Idempotency: if a verify task already exists for this request, do nothing.
        if Task.objects.filter(
            source_type=Task.SOURCE_PAYMENT_VERIFY,
            source_request=request_obj,
            status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
        ).exists():
            logger.debug(
                "PaymentConfirmedTrigger: open verify task already exists for request %s, skipping.",
                request_obj.pk,
            )
            return

        # Resolve verifier: prefer the person who processed the payment.
        verifier = closed.assignee if closed else None
        if verifier is None:
            # Closed payment task wasn't open — try to find it in any status.
            prior = (
                Task.objects.filter(
                    source_type=Task.SOURCE_REQUEST_APPROVED,
                    source_request=request_obj,
                )
                .select_related("assignee")
                .order_by("-created_at")
                .first()
            )
            if prior is not None:
                verifier = prior.assignee

        # Fallback to the role-based resolution if no prior task is available.
        if verifier is None:
            verifier = task_service.assignee_for_payment(request_obj)

        if verifier is None:
            logger.warning(
                "PaymentConfirmedTrigger: no verifier resolvable for request %s, skipping verify task.",
                request_obj.pk,
            )
            return

        task_service.create_task(
            tenant=request_obj.tenant,
            assignee=verifier,
            title=f"Проверить проведённую оплату по заявке #{request_obj.pk}",
            description=request_obj.title or "",
            created_by=None,
            source_type=Task.SOURCE_PAYMENT_VERIFY,
            source_request=request_obj,
        )


task_trigger_registry.register(PaymentConfirmedTrigger())
