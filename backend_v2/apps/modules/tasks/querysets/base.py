from __future__ import annotations

import abc

from django.db.models import QuerySet


class AbstractTaskScope(abc.ABC):
    """Contract for all task visibility scopes.

    Adding a new scope = new subclass + one entry in resolver.py.
    Never edit existing scopes to handle a new role.
    """

    @abc.abstractmethod
    def filter_queryset(self, qs: QuerySet, user, tenant) -> QuerySet:
        raise NotImplementedError
