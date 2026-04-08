from rest_framework import viewsets
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework import serializers
from rest_framework.views import APIView
from django.db import IntegrityError
from django.db.models import Exists, OuterRef, Q, Subquery

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.modules.bank_expenses.tashkent_dates import (
    TashkentFlexibleDateField,
    doc_date_candidates_for_composite_lookup,
)
from apps.modules.requests.models import Request
from apps.tenants.permissions import HasEffectiveModuleAccess
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


class BankExpenseViewSet(viewsets.ModelViewSet):
    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = BankExpenseSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return BankExpense.objects.none()
        request_subquery = Request.objects.filter(
            tenant=tenant,
            payment_type__in=(
                Request.PAYMENT_TYPE_TRANSFER,
                Request.PAYMENT_TYPE_TOPUP,
            ),
        ).filter(
            Q(expense_ref_id=OuterRef("id"))
            | (Q(expense_id=OuterRef("doc_no")) & Q(expense_year=OuterRef("expense_year")))
        )
        paid_request_subquery = request_subquery.filter(status=Request.STATUS_PAYED)
        qs = BankExpense.objects.filter(tenant=tenant).annotate(
            has_request=Exists(request_subquery),
            has_paid_request=Exists(paid_request_subquery),
            matched_request_id=Subquery(request_subquery.order_by("-created_at").values("id")[:1]),
        )
        vendor_search = (self.request.query_params.get("vendor_search") or "").strip()
        if vendor_search:
            qs = qs.filter(
                Q(vendor__name__icontains=vendor_search)
                | Q(vendor__inn__icontains=vendor_search)
                | Q(vendor__account_number__icontains=vendor_search)
            )
        return qs

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


class BankRevenueViewSet(viewsets.ModelViewSet):
    module_key = "bank"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = BankRevenueSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return BankRevenue.objects.none()
        return BankRevenue.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

