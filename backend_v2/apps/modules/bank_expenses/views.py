from rest_framework import viewsets
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework import serializers
from django.db import IntegrityError
from django.db.models import Exists, OuterRef, Subquery

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.modules.requests.models import Request
from apps.tenants.permissions import HasEffectiveModuleAccess


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
            expense_id=OuterRef("doc_no"),
        )
        paid_request_subquery = request_subquery.filter(status=Request.STATUS_PAYED)
        return BankExpense.objects.filter(tenant=tenant).annotate(
            has_request=Exists(request_subquery),
            has_paid_request=Exists(paid_request_subquery),
            matched_request_id=Subquery(request_subquery.order_by("-created_at").values("id")[:1]),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        incoming_id = request.data.get("id")
        if incoming_id in (None, ""):
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                serializer.save(tenant=tenant, created_by=request.user)
            except IntegrityError as exc:
                raise ValidationError({"detail": "Could not create bank expense with this payload."}) from exc
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

        try:
            normalized_id = int(incoming_id)
        except (TypeError, ValueError):
            raise ValidationError({"id": "ID must be an integer."})

        instance = BankExpense.objects.filter(tenant=tenant, id=normalized_id).first()
        if instance:
            # Full replace of editable fields on POST when id is provided.
            serializer = self.get_serializer(instance=instance, data=request.data, partial=False)
            serializer.is_valid(raise_exception=True)
            try:
                serializer.save()
            except IntegrityError as exc:
                raise ValidationError({"detail": "Could not update bank expense with this payload."}) from exc
            return Response(serializer.data, status=status.HTTP_200_OK)

        if BankExpense.objects.filter(id=normalized_id).exists():
            raise ValidationError({"id": "This ID already exists in another tenant."})

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(id=normalized_id, tenant=tenant, created_by=request.user)
        except IntegrityError as exc:
            raise ValidationError({"id": "Could not create bank expense with this ID."}) from exc
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=["post", "patch"], url_path="by-composite-key")
    def by_composite_key(self, request, *args, **kwargs):
        """
        Upsert bank expense by composite unique key.

        URL: /api/bank/expenses/by-composite-key/
        Body must contain: doc_no, doc_date, debit_turnover, payment_purpose
        """

        class _CompositeKeySerializer(serializers.Serializer):
            doc_no = serializers.CharField(allow_blank=False)
            doc_date = serializers.DateField()
            debit_turnover = serializers.DecimalField(max_digits=18, decimal_places=2)
            payment_purpose = serializers.CharField(allow_blank=False)

        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        key_ser = _CompositeKeySerializer(data=request.data)
        key_ser.is_valid(raise_exception=True)
        key = key_ser.validated_data

        instance = BankExpense.objects.filter(
            tenant=tenant,
            doc_no=key["doc_no"],
            doc_date=key["doc_date"],
            debit_turnover=key["debit_turnover"],
            payment_purpose=key["payment_purpose"],
        ).first()

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
        return BankRevenue.objects.filter(tenant_subdomain=tenant.subdomain)

    def perform_create(self, serializer):
        serializer.save(tenant_subdomain=self.request.tenant.subdomain, created_by=self.request.user)

