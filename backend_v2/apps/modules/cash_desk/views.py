from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.cash_desk.serializers import CashDeskConfigWriteSerializer, TransferTargetWriteSerializer
from apps.modules.cash_desk.services_config import config_payload, save_config
from apps.modules.cash_desk.transfer_target import save_transfer_target
from apps.modules.requests.models import Request
from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import HasEffectiveModuleAccess, IsTenantAdminOrDirector


class CashDeskConfigView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdminOrDirector]

    def get(self, request):
        return Response(config_payload(request.tenant))

    def put(self, request):
        ser = CashDeskConfigWriteSerializer(data=request.data, context={"tenant": request.tenant})
        ser.is_valid(raise_exception=True)
        save_config(tenant=request.tenant, data=ser.validated_data, actor=request.user)
        return Response(config_payload(request.tenant))


class CashTransferTargetView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "requests"

    def put(self, request, request_id: int):
        req = get_object_or_404(Request, pk=request_id, tenant=request.tenant)
        user = request.user
        allowed = (
            req.created_by_id == user.id
            or req.requester_id == user.id
            or TenantUserRole.objects.filter(
                tenant=request.tenant,
                user=user,
                role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR],
            ).exists()
        )
        if not allowed:
            raise PermissionDenied("Нет доступа к этой заявке.")
        ser = TransferTargetWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        target = save_transfer_target(
            request_obj=req,
            to_wallet_id=ser.validated_data["to_wallet_id"],
            to_amount=ser.validated_data.get("to_amount"),
            user=user,
        )
        return Response(
            {
                "request_id": req.id,
                "to_wallet_id": target.to_wallet_id,
                "to_amount": str(target.to_amount),
                "currency": target.to_wallet.currency,
            }
        )
