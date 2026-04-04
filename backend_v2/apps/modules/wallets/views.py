from django.db.models import ProtectedError
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.modules.wallets.models import CashRegister, Wallet
from apps.modules.wallets.serializers import CashRegisterSerializer, WalletSerializer
from apps.tenants.permissions import (
    HasEffectiveModuleAccess,
    HasWalletsFinancialWriteAccess,
)


class CashRegisterViewSet(viewsets.ModelViewSet):
    module_key = "wallets"
    serializer_class = CashRegisterSerializer

    def get_permissions(self):
        perms = [IsAuthenticated(), HasEffectiveModuleAccess()]
        if self.action in ("create", "update", "partial_update", "destroy"):
            perms.append(HasWalletsFinancialWriteAccess())
        return perms

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CashRegister.objects.none()
        qs = CashRegister.objects.filter(tenant=tenant).select_related("wallet").order_by(
            "sort_order", "id"
        )
        p = self.request.query_params
        if (raw := p.get("is_active")) is not None:
            low = raw.lower()
            if low in ("1", "true", "yes"):
                qs = qs.filter(is_active=True)
            elif low in ("0", "false", "no"):
                qs = qs.filter(is_active=False)
        if cur := (p.get("currency") or "").strip():
            qs = qs.filter(currency=cur)
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Нельзя удалить кассу: есть связанные операции."},
                status=status.HTTP_409_CONFLICT,
            )


class WalletViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    module_key = "wallets"
    serializer_class = WalletSerializer

    def get_permissions(self):
        perms = [IsAuthenticated(), HasEffectiveModuleAccess()]
        if self.action in ("partial_update", "update"):
            perms.append(HasWalletsFinancialWriteAccess())
        return perms

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Wallet.objects.none()
        return Wallet.objects.filter(tenant=tenant).select_related(
            "cash_register", "bank_account", "corporate_card_account"
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
