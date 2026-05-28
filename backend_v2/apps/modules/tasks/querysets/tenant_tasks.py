from __future__ import annotations

from django.db.models import QuerySet

from apps.modules.tasks.querysets.base import AbstractTaskScope


class TenantTasksScope(AbstractTaskScope):
    """Admins and directors — see all tasks within the active tenant."""

    def filter_queryset(self, qs: QuerySet, user, tenant) -> QuerySet:
        return qs.filter(tenant=tenant)
