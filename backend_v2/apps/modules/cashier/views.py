from rest_framework import viewsets
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import IntegrityError
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.cashier.serializers import CashExpenseSerializer, CashRevenueSerializer
from apps.modules.requests.expense_compliance import annotate_cash_expense_compliance
from apps.tenants.permissions import HasEffectiveModuleAccess
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import balances_for_tenant_channel


class CashBalancesView(APIView):
    module_key = "cash"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response([])
        return Response(
            balances_for_tenant_channel(tenant_id=tenant.id, wallet_type=Wallet.Type.CASH)
        )


class CashExpenseViewSet(viewsets.ModelViewSet):
    module_key = "cash"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CashExpenseSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CashExpense.objects.none()
        qs = annotate_cash_expense_compliance(
            CashExpense.objects.filter(tenant=tenant),
            tenant=tenant,
        )
        if self.action == "list":
            qs = qs.filter(wallet__is_visible_in_cash_section=True)
        vendor_search = (self.request.query_params.get("vendor_search") or "").strip()
        if vendor_search:
            qs = qs.filter(Q(title__icontains=vendor_search) | Q(vendor__name__icontains=vendor_search))
        return qs

    def perform_create(self, serializer):
        try:
            serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        except IntegrityError as exc:
            raise ValidationError({"external_id": "This id is already used for this year."}) from exc

    def perform_update(self, serializer):
        try:
            serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"external_id": "This id is already used for this year."}) from exc

    @action(detail=False, methods=["patch"], url_path="by-expense-id-year")
    def update_by_expense_id_year(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        raw_expense_id = request.data.get("expense_id", request.data.get("external_id"))
        raw_year = request.data.get("expense_year")
        if raw_expense_id in (None, ""):
            raise ValidationError({"expense_id": "This field is required."})
        if raw_year in (None, ""):
            raise ValidationError({"expense_year": "This field is required."})

        expense_id = str(raw_expense_id).strip()
        try:
            expense_year = int(raw_year)
        except (TypeError, ValueError):
            raise ValidationError({"expense_year": "Expense year must be an integer."})

        instance = CashExpense.objects.filter(
            tenant=tenant,
            external_id=expense_id,
            expense_year=expense_year,
        ).first()
        if not instance:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = dict(request.data)
        if "external_id" not in payload:
            payload["external_id"] = expense_id

        serializer = self.get_serializer(instance=instance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"external_id": "This id is already used for this year."}) from exc
        return Response(serializer.data, status=status.HTTP_200_OK)


class CashRevenueViewSet(viewsets.ModelViewSet):
    module_key = "cash"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CashRevenueSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CashRevenue.objects.none()
        qs = CashRevenue.objects.filter(tenant=tenant)
        if self.action == "list":
            qs = qs.filter(wallet__is_visible_in_cash_section=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

