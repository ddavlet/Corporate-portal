from django.db import IntegrityError
from django.db.models import Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import PortalCursorPagination
from apps.common.query_params import parse_bool_query, parse_date_query, parse_decimal_query
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.modules.bank_expenses.tashkent_dates import (
    TashkentFlexibleDateField,
    doc_date_candidates_for_composite_lookup,
)
from apps.modules.requests.expense_compliance import annotate_bank_expense_compliance, filter_expenses_missing_request
from apps.modules.requests.models import Request
from apps.tenants.permissions import HasEffectiveModuleAccess, IsTenantAdminForRecordEdit
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import balances_for_tenant_channel


class BankBalancesView(APIView):
    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response([])
        return Response(
            balances_for_tenant_channel(tenant_id=tenant.id, wallet_type=Wallet.Type.BANK)
        )


class BankExpenseCursorPagination(PortalCursorPagination):
    ordering = "-doc_date,-process_date,-id"


class BankRevenueCursorPagination(PortalCursorPagination):
    ordering = "-doc_date,-process_date,-id"


class BankExpenseViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess, IsTenantAdminForRecordEdit]
    serializer_class = BankExpenseSerializer
    pagination_class = BankExpenseCursorPagination
    ordering_fields = ["doc_date", "process_date", "debit_turnover", "id", "doc_no"]
    ordering = ["-doc_date", "-process_date", "-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return BankExpense.objects.none()
        qs = annotate_bank_expense_compliance(
            BankExpense.objects.filter(tenant=tenant),
            tenant=tenant,
        )
        vendor_search = (self.request.query_params.get("vendor_search") or "").strip()
        if vendor_search:
            qs = qs.filter(
                Q(vendor__name__icontains=vendor_search)
                | Q(vendor__inn__icontains=vendor_search)
                | Q(vendor__account_number__icontains=vendor_search)
            )
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(doc_no__icontains=search)
                | Q(payment_purpose__icontains=search)
                | Q(vendor__name__icontains=search)
            )
        doc_from = parse_date_query(self.request, "doc_from")
        doc_to = parse_date_query(self.request, "doc_to")
        if doc_from:
            qs = qs.filter(doc_date__gte=doc_from)
        if doc_to:
            qs = qs.filter(doc_date__lte=doc_to)
        amount_min = parse_decimal_query(self.request, "amount_min")
        amount_max = parse_decimal_query(self.request, "amount_max")
        if amount_min is not None:
            qs = qs.filter(debit_turnover__gte=amount_min)
        if amount_max is not None:
            qs = qs.filter(debit_turnover__lte=amount_max)
        if parse_bool_query(self.request, "missing_request"):
            qs = filter_expenses_missing_request(
                qs,
                tenant=tenant,
                payment_type=Request.PAYMENT_TYPE_TRANSFER,
            )
        return qs.order_by("-doc_date", "-process_date", "-id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    @action(detail=False, methods=["post", "patch"], url_path="by-composite-key")
    def by_composite_key(self, request, *args, **kwargs):
        """
        Upsert bank expense by composite unique key.

        URL: /api/bank/expenses/by-composite-key/
        Body must contain: doc_no, doc_date, debit_turnover, payment_purpose
        """

        class _CompositeKeySerializer(serializers.Serializer):
            doc_no = serializers.CharField(allow_blank=False)
            doc_date = TashkentFlexibleDateField()
            debit_turnover = serializers.DecimalField(max_digits=18, decimal_places=2)
            payment_purpose = serializers.CharField(allow_blank=False)

        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        key_ser = _CompositeKeySerializer(data=request.data)
        key_ser.is_valid(raise_exception=True)
        key = key_ser.validated_data

        raw_doc_date = request.data.get("doc_date")
        doc_dates = doc_date_candidates_for_composite_lookup(raw_doc_date)
        if not doc_dates:
            doc_dates = [key["doc_date"]]

        instance = None
        for doc_d in doc_dates:
            instance = BankExpense.objects.filter(
                tenant=tenant,
                doc_no=key["doc_no"],
                doc_date=doc_d,
                debit_turnover=key["debit_turnover"],
                payment_purpose=key["payment_purpose"],
            ).first()
            if instance:
                break

        if request.method == "PATCH":
            if not instance:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

            serializer = self.get_serializer(instance=instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                serializer.save()
            except IntegrityError as exc:
                raise ValidationError(
                    {"detail": "Could not update bank expense with this payload (unique constraint conflict?)."}
                ) from exc

            return Response(serializer.data, status=status.HTTP_200_OK)

        # POST: upsert by composite key (create if missing, otherwise update).
        if instance:
            serializer = self.get_serializer(instance=instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                serializer.save()
            except IntegrityError as exc:
                raise ValidationError(
                    {"detail": "Could not update bank expense with this payload (unique constraint conflict?)."}
                ) from exc
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant=tenant, created_by=request.user)
        except IntegrityError as exc:
            raise ValidationError(
                {"detail": "Could not create bank expense with this payload (unique constraint conflict?)."}
            ) from exc
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class BankRevenueViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess, IsTenantAdminForRecordEdit]
    serializer_class = BankRevenueSerializer
    pagination_class = BankRevenueCursorPagination
    ordering_fields = ["doc_date", "process_date", "kredit_turnover", "id"]
    ordering = ["-doc_date", "-process_date", "-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return BankRevenue.objects.none()
        qs = BankRevenue.objects.filter(tenant=tenant)
        doc_from = parse_date_query(self.request, "doc_from")
        doc_to = parse_date_query(self.request, "doc_to")
        if doc_from:
            qs = qs.filter(doc_date__gte=doc_from)
        if doc_to:
            qs = qs.filter(doc_date__lte=doc_to)
        return qs.order_by("-doc_date", "-process_date", "-id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

