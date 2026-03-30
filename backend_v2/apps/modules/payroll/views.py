from django.db.models import Count, Exists, OuterRef, Prefetch, Subquery, Sum
from django.db.models.functions import Coalesce
from django.db.models import DecimalField, Value
from decimal import Decimal

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.payroll.constants import MODULE_KEY, SALARY_CATEGORY
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.payroll.serializers import (
    PayrollDocumentDetailSerializer,
    PayrollDocumentListSerializer,
)
from apps.modules.requests.models import Request
from apps.tenants.permissions import HasEffectiveModuleAccess


class PayrollDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    lookup_field = "pk"

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return PayrollDocument.objects.none()

        request_subquery = Request.objects.filter(
            tenant=tenant,
            payment_type=Request.PAYMENT_TYPE_CASH,
            category=SALARY_CATEGORY,
            expense_id=OuterRef("doc_id"),
        )
        paid_request_subquery = request_subquery.filter(status=Request.STATUS_PAYED)

        qs = (
            PayrollDocument.objects.filter(tenant=tenant)
            .annotate(
                total_sum=Coalesce(Sum("lines__sum"), Value(Decimal("0")), output_field=DecimalField(max_digits=18, decimal_places=2)),
                lines_count=Count("lines", distinct=True),
                has_request=Exists(request_subquery),
                has_paid_request=Exists(paid_request_subquery),
                matched_request_id=Subquery(request_subquery.order_by("-id").values("id")[:1]),
            )
            .order_by("-created_at", "-id")
        )

        doc_id = (self.request.query_params.get("doc_id") or "").strip()
        if doc_id:
            qs = qs.filter(doc_id__icontains=doc_id)

        employee_search = (self.request.query_params.get("employee_search") or "").strip()
        if employee_search:
            qs = qs.filter(
                Exists(
                    PayrollLine.objects.filter(
                        document_id=OuterRef("pk"),
                        employee__icontains=employee_search,
                    )
                )
            )

        period_from = (self.request.query_params.get("period_from") or "").strip()
        if period_from:
            qs = qs.filter(
                Exists(
                    PayrollLine.objects.filter(
                        document_id=OuterRef("pk"),
                        period_start__gte=period_from,
                    )
                )
            )
        period_to = (self.request.query_params.get("period_to") or "").strip()
        if period_to:
            qs = qs.filter(
                Exists(
                    PayrollLine.objects.filter(
                        document_id=OuterRef("pk"),
                        period_end__lte=period_to,
                    )
                )
            )

        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("lines", queryset=PayrollLine.objects.order_by("line_no", "id"))
            )
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PayrollDocumentDetailSerializer
        return PayrollDocumentListSerializer
