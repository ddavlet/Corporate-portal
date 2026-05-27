from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Dispatch escalation events for tasks stale for more than 3 days."

    def handle(self, *args, **options) -> None:
        from apps.modules.tasks.models import Task
        from apps.modules.tasks.triggers.registry import task_trigger_registry

        threshold = timezone.now() - timedelta(days=3)
        stale_qs = (
            Task.objects.filter(
                status__in=[Task.STATUS_NEW, Task.STATUS_IN_PROGRESS],
                updated_at__lt=threshold,
            )
            .select_related("tenant", "source_request")
        )

        count = 0
        for task in stale_qs.iterator():
            task_trigger_registry.dispatch("escalation", task=task)
            count += 1

        self.stdout.write(f"check_task_escalations: {count} stale task(s) processed.")
