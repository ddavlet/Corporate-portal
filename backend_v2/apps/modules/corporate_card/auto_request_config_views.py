from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.corporate_card.auto_request_config import (
    card_auto_request_config_payload,
    get_card_wallet_or_404,
    save_card_auto_request_config,
)
from apps.modules.corporate_card.auto_request_config_serializers import CardExpenseAutoRequestConfigWriteSerializer
from apps.tenants.permissions import IsTenantAdmin, IsTenantModuleEnabled


class CardExpenseAutoRequestConfigView(APIView):
    """Per-card settings of automatic requests for card expenses; tenant admin only."""

    module_key = "corporate_card"
    permission_classes = [IsAuthenticated, IsTenantModuleEnabled, IsTenantAdmin]

    def get(self, request, wallet_id: int):
        wallet = get_card_wallet_or_404(tenant=request.tenant, wallet_id=wallet_id)
        return Response(card_auto_request_config_payload(tenant=request.tenant, wallet=wallet))

    def patch(self, request, wallet_id: int):
        wallet = get_card_wallet_or_404(tenant=request.tenant, wallet_id=wallet_id)
        ser = CardExpenseAutoRequestConfigWriteSerializer(
            data=request.data,
            context={"tenant": request.tenant, "wallet": wallet},
        )
        ser.is_valid(raise_exception=True)
        save_card_auto_request_config(
            tenant=request.tenant,
            wallet=wallet,
            data=ser.validated_data,
            actor=request.user,
        )
        return Response(card_auto_request_config_payload(tenant=request.tenant, wallet=wallet))
