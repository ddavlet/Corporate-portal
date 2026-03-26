from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.requests.models import Request
from apps.modules.requests.serializers import PortalRequestSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess


class PortalRequestViewSet(viewsets.ModelViewSet):
    """
    Placeholder CRUD for the Requests module.
    Replace/add fields once you provide the exact requests schema.
    """

    module_key = "requests"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = PortalRequestSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Request.objects.none()
        return Request.objects.filter(tenant=tenant).order_by("-submitted_at")

    def perform_create(self, serializer):
        tenant = self.request.tenant
        serializer.save(tenant=tenant)

