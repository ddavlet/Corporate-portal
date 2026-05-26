from django.db import IntegrityError
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import PortalCursorPagination
from apps.common.query_params import parse_bool_query, parse_date_query, parse_decimal_query
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.cashier.serializers import CashExpenseSerializer, CashRevenueSerializer
from apps.modules.requests.expense_compliance import annotate_cash_expense_compliance, filter_expenses_missing_request
from apps.modules.requests.models import Request
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


class CashExpenseCursorPagination(PortalCursorPagination):
    ordering = "-expense_at,-id"


class CashRevenueCursorPagination(PortalCursorPagination):
    ordering = "-created_at,-id"


class CashExpenseViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "cash"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CashExpenseSerializer
    pagination_class = CashExpenseCursorPagination
    ordering_fields = ["expense_at", "amount", "id", "created_at", "external_id"]
    ordering = ["-expense_at", "-id"]

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
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(vendor__name__icontains=search) | Q(external_id__icontains=search))
        expense_from = parse_date_query(self.request, "expense_from")
        expense_to = parse_date_query(self.request, "expense_to")
        if expense_from:
            qs = qs.filter(expense_at__date__gte=expense_from)
        if expense_to:
            qs = qs.filter(expense_at__date__lte=expense_to)
        amount_min = parse_decimal_query(self.request, "amount_min")
        amount_max = parse_decimal_query(self.request, "amount_max")
        if amount_min is not None:
            qs = qs.filter(amount__gte=amount_min)
        if amount_max is not None:
            qs = qs.filter(amount__lte=amount_max)
        wallet_id = (self.request.query_params.get("wallet") or "").strip()
        if wallet_id.isdigit():
            qs = qs.filter(wallet_id=int(wallet_id))
        currency = (self.request.query_params.get("currency") or "").strip()
        if currency:
            qs = qs.filter(currency=currency)
        if parse_bool_query(self.request, "missing_request"):
            qs = filter_expenses_missing_request(
                qs,
                tenant=tenant,
                payment_type=Request.PAYMENT_TYPE_CASH,
            )
        return qs.order_by("-expense_at", "-id")

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


class CashRevenueViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "cash"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CashRevenueSerializer
    pagination_class = CashRevenueCursorPagination
    ordering_fields = ["revenue_at", "created_at", "total_sum", "id"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CashRevenue.objects.none()
        qs = CashRevenue.objects.filter(tenant=tenant)
        if self.action == "list":
            qs = qs.filter(wallet__is_visible_in_cash_section=True)
        revenue_from = parse_date_query(self.request, "expense_from")
        revenue_to = parse_date_query(self.request, "expense_to")
        if revenue_from:
            qs = qs.filter(revenue_at__date__gte=revenue_from)
        if revenue_to:
            qs = qs.filter(revenue_at__date__lte=revenue_to)
        return qs.order_by("-created_at", "-id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

