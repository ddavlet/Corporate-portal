from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.cashier.serializers import CashExpenseSerializer, CashRevenueSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess


class CashExpenseViewSet(viewsets.ModelViewSet):
    module_key = "cash"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CashExpenseSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CashExpense.objects.none()
        return CashExpense.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class CashRevenueViewSet(viewsets.ModelViewSet):
    module_key = "cash"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CashRevenueSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CashRevenue.objects.none()
        return CashRevenue.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

