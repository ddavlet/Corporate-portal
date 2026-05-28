from __future__ import annotations

from django.db.models import QuerySet

from apps.modules.tasks.querysets.base import AbstractTaskScope


class OwnTasksScope(AbstractTaskScope):
    """Regular users — see only tasks assigned to themselves within this tenant."""

    def filter_queryset(self, qs: QuerySet, user, tenant) -> QuerySet:
        # Tenant predicate is non-negotiable: users may be members of multiple tenants
        # and we never want a task from tenant B to leak into tenant A's view.
        return qs.filter(assignee=user, tenant=tenant)
