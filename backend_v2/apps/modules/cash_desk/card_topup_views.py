from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.cash_desk.card_topup_config import card_topup_config_payload, save_card_topup_config
from apps.modules.cash_desk.card_topup_serializers import CardTopupNotifyConfigWriteSerializer
from apps.tenants.permissions import IsTenantAdminOrDirector


class CardTopupNotifyConfigView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdminOrDirector]

    def get(self, request):
        return Response(card_topup_config_payload(request.tenant))

    def put(self, request):
        ser = CardTopupNotifyConfigWriteSerializer(data=request.data, context={"tenant": request.tenant})
        ser.is_valid(raise_exception=True)
        save_card_topup_config(tenant=request.tenant, data=ser.validated_data, actor=request.user)
        return Response(card_topup_config_payload(request.tenant))
