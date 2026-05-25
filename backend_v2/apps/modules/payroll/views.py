from django.db.models import Exists, OuterRef, Prefetch

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.modules.payroll.constants import MODULE_KEY
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.payroll.serializers import (
    PayrollDocumentDetailSerializer,
    PayrollDocumentListSerializer,
)
from apps.modules.requests.expense_compliance import annotate_payroll_compliance
from apps.tenants.permissions import HasEffectiveModuleAccess


class PayrollDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    lookup_field = "pk"

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return PayrollDocument.objects.none()

        qs = annotate_payroll_compliance(
            PayrollDocument.objects.filter(tenant=tenant),
            tenant=tenant,
        ).order_by("-created_at", "-id")

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
