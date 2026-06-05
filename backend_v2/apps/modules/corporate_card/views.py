from django.db.models import Q
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import PortalCursorPagination
from apps.common.query_params import parse_bool_query, parse_date_query, parse_decimal_query
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import CardExpenseSerializer, CardRevenueSerializer
from apps.modules.requests.expense_compliance import annotate_card_expense_compliance, filter_expenses_missing_request
from apps.modules.requests.models import Request
from apps.tenants.permissions import HasEffectiveModuleAccess
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import balances_for_tenant_channel


class CorporateCardBalancesView(APIView):
    module_key = "corporate_card"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response([])
        return Response(
            balances_for_tenant_channel(
                tenant_id=tenant.id, wallet_type=Wallet.Type.CORPORATE_CARD
            )
        )


class CardExpenseCursorPagination(PortalCursorPagination):
    ordering = "-expense_at,-id"


class CardRevenueCursorPagination(PortalCursorPagination):
    ordering = "-revenue_at,-id"


class CardExpenseViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "corporate_card"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CardExpenseSerializer
    pagination_class = CardExpenseCursorPagination
    ordering_fields = ["expense_at", "amount", "id", "created_at"]
    ordering = ["-expense_at", "-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CardExpense.objects.none()
        qs = annotate_card_expense_compliance(
            CardExpense.objects.filter(tenant=tenant),
            tenant=tenant,
        )
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(vendor__name__icontains=search))
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
        if parse_bool_query(self.request, "missing_request"):
            qs = filter_expenses_missing_request(
                qs,
                tenant=tenant,
                payment_type=Request.PAYMENT_TYPE_CARD,
            )
        return qs.order_by("-expense_at", "-id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)


class CardRevenueViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "corporate_card"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = CardRevenueSerializer
    pagination_class = CardRevenueCursorPagination
    ordering_fields = ["revenue_at", "total_sum", "id", "created_at"]
    ordering = ["-revenue_at", "-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return CardRevenue.objects.none()
        qs = CardRevenue.objects.filter(tenant=tenant)
        revenue_from = parse_date_query(self.request, "expense_from")
        revenue_to = parse_date_query(self.request, "expense_to")
        if revenue_from:
            qs = qs.filter(revenue_at__date__gte=revenue_from)
        if revenue_to:
            qs = qs.filter(revenue_at__date__lte=revenue_to)
        return qs.order_by("-revenue_at", "-id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

