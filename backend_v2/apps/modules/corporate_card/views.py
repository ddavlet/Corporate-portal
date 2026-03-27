from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import CardExpenseSerializer, CardRevenueSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess


class CardExpenseViewSet(viewsets.ModelViewSet):
    module_key = "corporate_card"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CardExpenseSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CardExpense.objects.none()
        return CardExpense.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)


class CardRevenueViewSet(viewsets.ModelViewSet):
    module_key = "corporate_card"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CardRevenueSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CardRevenue.objects.none()
        return CardRevenue.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

