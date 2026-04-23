from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.investments.models import InvestPayoutSchedule, InvestReturn, ProjectInvestment
from apps.modules.investments.serializers import (
    InvestPayoutScheduleSerializer,
    InvestReturnSerializer,
    ProjectInvestmentSerializer,
)
from apps.tenants.permissions import HasEffectiveModuleAccess


class _InvestmentsTenantViewSet(viewsets.ModelViewSet):
    module_key = "investments"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return self.queryset.none()
        return self.queryset.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)


class InvestReturnViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestReturnSerializer
    queryset = InvestReturn.objects.all()


class InvestPayoutScheduleViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestPayoutScheduleSerializer
    queryset = InvestPayoutSchedule.objects.all()


class ProjectInvestmentViewSet(_InvestmentsTenantViewSet):
    serializer_class = ProjectInvestmentSerializer
    queryset = ProjectInvestment.objects.all()
