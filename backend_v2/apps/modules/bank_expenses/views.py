from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess


class BankExpenseViewSet(viewsets.ModelViewSet):
    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = BankExpenseSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return BankExpense.objects.none()
        return BankExpense.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class BankRevenueViewSet(viewsets.ModelViewSet):
    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = BankRevenueSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return BankRevenue.objects.none()
        return BankRevenue.objects.filter(tenant_subdomain=tenant.subdomain)

    def perform_create(self, serializer):
        serializer.save(tenant_subdomain=self.request.tenant.subdomain)

