from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.kapitalbank.accounts import pending_accounts
from apps.modules.kapitalbank.models import BankAccountLink, KapitalbankConnection
from apps.modules.kapitalbank.serializers import PendingAccountSerializer, UntrackedAccountSerializer
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


class UntrackedAccountsView(APIView):
    """Pending and ignored (service) accounts of the tenant, for the Bank page's account list."""

    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        links = BankAccountLink.objects.filter(
            tenant=request.tenant, decision__in=[BankAccountLink.PENDING, BankAccountLink.IGNORED]
        )
        # "ignored" sorts before "pending" alphabetically, so order by the API status explicitly.
        ordered = sorted(links, key=lambda link: (link.decision == BankAccountLink.IGNORED, link.account_no))
        return Response(UntrackedAccountSerializer(ordered, many=True).data)
