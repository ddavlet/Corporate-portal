from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.cash_withdrawals.serializers import CashWithdrawalConfigWriteSerializer
from apps.modules.cash_withdrawals.services import config_payload, save_config
from apps.tenants.permissions import IsTenantAdminOrDirector


class CashWithdrawalConfigView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdminOrDirector]

    def get(self, request):
        return Response(config_payload(request.tenant))

    def put(self, request):
        ser = CashWithdrawalConfigWriteSerializer(data=request.data, context={"tenant": request.tenant})
        ser.is_valid(raise_exception=True)
        save_config(tenant=request.tenant, data=ser.validated_data, actor=request.user)
        return Response(config_payload(request.tenant))
