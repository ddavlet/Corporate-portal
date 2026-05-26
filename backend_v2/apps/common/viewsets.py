from rest_framework import filters

from apps.common.pagination import PortalCursorPagination


class PortalListViewSetMixin:
    pagination_class = PortalCursorPagination
    filter_backends = [filters.OrderingFilter]


class NoPortalPaginationMixin:
    pagination_class = None
