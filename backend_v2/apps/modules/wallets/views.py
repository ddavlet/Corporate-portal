from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.wallets.models import BankAccount, CashRegister, CorporateCardAccount, Wallet
from apps.modules.wallets.serializers import (
    BankAccountSerializer,
    CashRegisterSerializer,
    CorporateCardAccountSerializer,
    WalletSerializer,
)
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
        instance = self.get_object()
        wallet = Wallet.objects.filter(cash_register=instance).first()
        if wallet:
            if CashExpense.objects.filter(wallet=wallet).exists() or CashRevenue.objects.filter(
                wallet=wallet
            ).exists():
                return Response(
                    {"detail": "Нельзя удалить кассу: есть кассовые операции."},
                    status=status.HTTP_409_CONFLICT,
                )
            try:
                with transaction.atomic():
                    wallet.delete()
                    instance.delete()
            except ProtectedError:
                return Response(
                    {"detail": "Нельзя удалить кассу: есть связанные данные."},
                    status=status.HTTP_409_CONFLICT,
                )
        else:
            instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BankAccountViewSet(viewsets.ModelViewSet):
    module_key = "wallets"
    serializer_class = BankAccountSerializer

    def get_permissions(self):
        perms = [IsAuthenticated(), HasEffectiveModuleAccess()]
        if self.action in ("create", "update", "partial_update", "destroy"):
            perms.append(HasWalletsFinancialWriteAccess())
        return perms

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return BankAccount.objects.none()
        return BankAccount.objects.filter(tenant=tenant).select_related("wallet").order_by("id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        wallet = Wallet.objects.filter(bank_account=instance).first()
        if wallet:
            if BankExpense.objects.filter(wallet=wallet).exists() or BankRevenue.objects.filter(
                wallet=wallet
            ).exists():
                return Response(
                    {"detail": "Нельзя удалить банковский счёт: есть операции по выписке."},
                    status=status.HTTP_409_CONFLICT,
                )
            try:
                with transaction.atomic():
                    wallet.delete()
                    instance.delete()
            except ProtectedError:
                return Response(
                    {"detail": "Нельзя удалить: есть связанные данные."},
                    status=status.HTTP_409_CONFLICT,
                )
        else:
            instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CorporateCardAccountViewSet(viewsets.ModelViewSet):
    module_key = "wallets"
    serializer_class = CorporateCardAccountSerializer

    def get_permissions(self):
        perms = [IsAuthenticated(), HasEffectiveModuleAccess()]
        if self.action in ("create", "update", "partial_update", "destroy"):
            perms.append(HasWalletsFinancialWriteAccess())
        return perms

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CorporateCardAccount.objects.none()
        qs = CorporateCardAccount.objects.filter(tenant=tenant).select_related("wallet").order_by(
            "currency", "id"
        )
        if cur := (self.request.query_params.get("currency") or "").strip():
            qs = qs.filter(currency=cur)
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        wallet = Wallet.objects.filter(corporate_card_account=instance).first()
        if wallet:
            if CardExpense.objects.filter(wallet=wallet).exists() or CardRevenue.objects.filter(
                wallet=wallet
            ).exists():
                return Response(
                    {"detail": "Нельзя удалить счёт корпкарты: есть операции по карте."},
                    status=status.HTTP_409_CONFLICT,
                )
            try:
                with transaction.atomic():
                    wallet.delete()
                    instance.delete()
            except ProtectedError:
                return Response(
                    {"detail": "Нельзя удалить счёт корпкарты: есть связанные данные."},
                    status=status.HTTP_409_CONFLICT,
                )
        else:
            instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        # partial_update() delegates here with request.method PATCH; disallow PUT only.
        if request.method.upper() == "PUT":
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        return super().update(request, *args, **kwargs)
