from django.db.models import Q
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.common.pagination import PortalCursorPagination
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.clients_debt.models import ClientDebtSnapshot
from apps.modules.clients_debt.serializers import ClientDebtSnapshotSerializer
from apps.modules.clients_debt.registry import MODULE_KEY
from apps.tenants.permissions import HasEffectiveModuleAccess


class ClientDebtCursorPagination(PortalCursorPagination):
    ordering = "-snapshot_at,-id"


class ClientDebtSnapshotViewSet(PortalListViewSetMixin, viewsets.ReadOnlyModelViewSet):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = ClientDebtSnapshotSerializer
    pagination_class = ClientDebtCursorPagination
    ordering_fields = ["snapshot_at", "client", "id", "amount"]
    ordering = ["-snapshot_at", "-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return ClientDebtSnapshot.objects.none()
        qs = ClientDebtSnapshot.objects.filter(tenant=tenant)
        client_search = (self.request.query_params.get("client_search") or "").strip()
        if client_search:
            qs = qs.filter(Q(client__icontains=client_search) | Q(client_id__icontains=client_search))
        doc_type = (self.request.query_params.get("doc_type") or "").strip()
        if doc_type:
            qs = qs.filter(doc_type=doc_type)
        return qs.order_by("-snapshot_at", "-id")

