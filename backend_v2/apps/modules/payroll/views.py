from django.db.models import Exists, OuterRef, Prefetch, Q

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.common.pagination import PortalCursorPagination
from apps.common.query_params import parse_bool_query, parse_date_query, parse_decimal_query
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.payroll.constants import MODULE_KEY
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.payroll.serializers import (
    PayrollDocumentDetailSerializer,
    PayrollDocumentListSerializer,
)
from apps.modules.requests.expense_compliance import annotate_payroll_compliance, filter_expenses_missing_request
from apps.tenants.permissions import HasEffectiveModuleAccess


class PayrollDocumentCursorPagination(PortalCursorPagination):
    ordering = "-created_at,-id"


class PayrollDocumentViewSet(PortalListViewSetMixin, viewsets.ReadOnlyModelViewSet):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    lookup_field = "pk"
    pagination_class = PayrollDocumentCursorPagination
    ordering_fields = ["created_at", "doc_id", "id"]
    ordering = ["-created_at", "-id"]

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

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(doc_id__icontains=search))

        created_from = parse_date_query(self.request, "created_from")
        created_to = parse_date_query(self.request, "created_to")
        if created_from:
            qs = qs.filter(created_at__date__gte=created_from)
        if created_to:
            qs = qs.filter(created_at__date__lte=created_to)

        amount_min = parse_decimal_query(self.request, "amount_min")
        amount_max = parse_decimal_query(self.request, "amount_max")
        if amount_min is not None:
            qs = qs.filter(total_sum__gte=amount_min)
        if amount_max is not None:
            qs = qs.filter(total_sum__lte=amount_max)

        has_request = parse_bool_query(self.request, "has_request")
        if has_request is True:
            qs = qs.filter(has_request=True)
        elif has_request is False:
            qs = qs.filter(has_request=False)

        if parse_bool_query(self.request, "missing_request"):
            qs = filter_expenses_missing_request(qs, tenant=tenant, payment_type="", payroll=True)

        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("lines", queryset=PayrollLine.objects.order_by("line_no", "id"))
            )
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PayrollDocumentDetailSerializer
        return PayrollDocumentListSerializer
