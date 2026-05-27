from __future__ import annotations

import logging

from apps.modules.tasks.triggers.base import AbstractTaskTrigger
from apps.modules.tasks.triggers.registry import task_trigger_registry

logger = logging.getLogger(__name__)


class EscalationTrigger(AbstractTaskTrigger):
    """Creates an escalation task for an admin/director when a task goes stale.

    Idempotent: skips creation if an open escalation task already exists for
    the same stale task (identified via source_expense_type + source_expense_id).
    """

    event_name = "escalation"

    def handle(self, *, task, **context) -> None:
        from django.contrib.auth import get_user_model

        from apps.modules.tasks.models import Task
        from apps.modules.tasks.services import task_service
        from apps.tenants.models import TenantUserRole

        User = get_user_model()
        directors = list(
            User.objects.filter(
                tenant_roles__tenant=task.tenant,
                tenant_roles__role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR],
            )
            .order_by("id")
            .distinct()
        )
        if not directors:
            logger.warning(
                "EscalationTrigger: no admin/director found in tenant %s for stale task %s.",
                task.tenant_id,
                task.pk,
            )
            return

        for assignee in directors:
            if Task.objects.filter(
                source_type=Task.SOURCE_ESCALATION,
                source_expense_type="task_escalation",
                source_expense_id=task.pk,
                assignee=assignee,
                status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
            ).exists():
                logger.debug(
                    "EscalationTrigger: open escalation task already exists for stale task %s assignee %s, skipping.",
                    task.pk,
                    assignee.pk,
                )
                continue

            task_service.create_task(
                tenant=task.tenant,
                assignee=assignee,
                title=f"Задача просрочена: {task.title}",
                description=f"Задача #{task.pk} не обновлялась более 3 дней.",
                created_by=None,
                source_type=Task.SOURCE_ESCALATION,
                source_approval=None,
                source_request=task.source_request,
                source_expense_type="task_escalation",
                source_expense_id=task.pk,
            )


task_trigger_registry.register(EscalationTrigger())
