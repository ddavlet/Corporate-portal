from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import CardExpenseSerializer, CardRevenueSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import balances_for_tenant_channel


class CorporateCardBalancesView(APIView):
    module_key = "corporate_card"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response([])
        return Response(
            balances_for_tenant_channel(
                tenant_id=tenant.id, wallet_type=Wallet.Type.CORPORATE_CARD
            )
        )


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

