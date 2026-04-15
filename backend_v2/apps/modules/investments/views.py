from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.investments.models import InvestReturn
from apps.modules.investments.serializers import InvestReturnSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess


class InvestReturnViewSet(viewsets.ModelViewSet):
    module_key = "investments"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = InvestReturnSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return InvestReturn.objects.none()
        return InvestReturn.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)
