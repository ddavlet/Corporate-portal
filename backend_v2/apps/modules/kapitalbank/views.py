from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.kapitalbank.accounts import pending_accounts
from apps.modules.kapitalbank.models import KapitalbankConnection
from apps.modules.kapitalbank.serializers import PendingAccountSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess


class PendingAccountsView(APIView):
    """Read-only hint for the Bank page: bank accounts still awaiting the owner's decision."""

    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = request.tenant
        enabled = KapitalbankConnection.objects.filter(tenant=tenant, is_enabled=True).exists()
        accounts = PendingAccountSerializer(pending_accounts(tenant), many=True).data if enabled else []
        return Response({"enabled": enabled, "accounts": accounts})
