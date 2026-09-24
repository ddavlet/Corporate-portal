import datetime as dt
from decimal import Decimal

from django.db.models import (
    DecimalField,
    Exists,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import PortalCursorPagination
from apps.common.query_params import parse_bool_query, parse_date_query, parse_decimal_query
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.payroll.constants import MODULE_KEY
from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine, PayrollPayout
from apps.modules.payroll.payouts import close_underpaid, create_payout_expense, document_label, payout_state
from apps.modules.payroll.permissions import HasPayrollPayoutAccess
from apps.modules.payroll.serializers import (
    EmployeeCreateSerializer,
    EmployeeSerializer,
    PayrollCloseUnderpaidSerializer,
    PayrollDocumentWorkflowDetailSerializer,
    PayrollDocumentWorkflowListSerializer,
    PayrollDraftSerializer,
    PayrollPayoutCreateSerializer,
)
from apps.modules.payroll.services import (
    accept_document,
    cancel_draft_document,
    copy_document,
    create_draft_document,
    update_draft_document,
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
        ).annotate(
            paid_total=Coalesce(
                Subquery(
                    PayrollPayout.objects.filter(document_id=OuterRef("pk"))
                    .values("document_id")
                    .annotate(s=Sum("amount"))
                    .values("s")[:1]
                ),
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
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

        status_raw = (self.request.query_params.get("status") or "").strip()
        if status_raw:
            qs = qs.filter(status=status_raw)
        elif self.action == "list":
            qs = qs.exclude(status=PayrollDocument.STATUS_CANCELLED)

        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("lines", queryset=PayrollLine.objects.order_by("line_no", "id"))
            )
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return PayrollDocumentWorkflowListSerializer
        return PayrollDocumentWorkflowDetailSerializer

    def _detail(self, document, status_code=status.HTTP_200_OK):
        # Fresh read without list filters (cancelled/status) so every action returns the document.
        fresh = PayrollDocument.objects.prefetch_related(
            Prefetch("lines", queryset=PayrollLine.objects.order_by("line_no", "id"))
        ).get(pk=document.pk)
        return Response(PayrollDocumentWorkflowDetailSerializer(fresh).data, status=status_code)

    def partial_update(self, request, *args, **kwargs):
        document = self.get_object()
        ser = PayrollDraftSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        update_draft_document(
            document=document,
            period_month=ser.validated_data["period_month"],
            kind=ser.validated_data["kind"],
            lines_data=ser.validated_data["lines"],
        )
        return self._detail(document)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        document = cancel_draft_document(document=self.get_object())
        return self._detail(document)

    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        new_document = copy_document(document=self.get_object(), user=request.user)
        return self._detail(new_document, status_code=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        document = self.get_object()
        accept_document(document=document, actor=request.user)
        return self._detail(document)


class PayrollDocumentCreateView(generics.CreateAPIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = PayrollDraftSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        document = create_draft_document(
            tenant=tenant,
            user=request.user,
            period_month=serializer.validated_data["period_month"],
            kind=serializer.validated_data["kind"],
            lines_data=serializer.validated_data["lines"],
        )
        fresh = PayrollDocument.objects.prefetch_related(
            Prefetch("lines", queryset=PayrollLine.objects.order_by("line_no", "id"))
        ).get(pk=document.pk)
        out = PayrollDocumentWorkflowDetailSerializer(fresh)
        return Response(out.data, status=status.HTTP_201_CREATED)


def _tenant_document(request, pk) -> PayrollDocument:
    tenant = getattr(request, "tenant", None)
    document = PayrollDocument.objects.filter(tenant=tenant, pk=pk).first()
    if document is None:
        raise NotFound("Начисление не найдено.")
    return document


def _serialize_state(state: dict) -> dict:
    def conv(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, (dt.date, dt.datetime)):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    return conv(state)


class PayrollPayoutStateView(APIView):
    permission_classes = [IsAuthenticated, HasPayrollPayoutAccess]

    def get(self, request, pk):
        return Response(_serialize_state(payout_state(_tenant_document(request, pk))))


class PayrollPayoutCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPayrollPayoutAccess]

    def post(self, request, pk):
        document = _tenant_document(request, pk)
        ser = PayrollPayoutCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        expense = create_payout_expense(
            document=document,
            wallet_id=ser.validated_data["wallet_id"],
            date=ser.validated_data["date"],
            items=ser.validated_data["items"],
            actor=request.user,
        )
        document.refresh_from_db()
        return Response(
            {"cash_expense_id": expense.id, "state": _serialize_state(payout_state(document))},
            status=status.HTTP_201_CREATED,
        )


class PayrollCloseUnderpaidView(APIView):
    permission_classes = [IsAuthenticated, HasPayrollPayoutAccess]

    def post(self, request, pk):
        document = _tenant_document(request, pk)
        ser = PayrollCloseUnderpaidSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        close_underpaid(document=document, actor=request.user, comment=ser.validated_data["comment"])
        fresh = PayrollDocument.objects.prefetch_related("lines").get(pk=document.pk)
        return Response(PayrollDocumentWorkflowDetailSerializer(fresh).data)


class PayablePayrollDocumentsView(APIView):
    permission_classes = [IsAuthenticated, HasPayrollPayoutAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        candidates = PayrollDocument.objects.filter(
            tenant=tenant,
            payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL,
            status=PayrollDocument.STATUS_ACCEPTED,
        ).order_by("-created_at", "-id")[:200]
        out = []
        for document in candidates:
            state = payout_state(document)
            if state["can_pay"]:
                out.append(
                    {
                        "id": document.id,
                        "label": document_label(document),
                        "period_month": document.period_month.isoformat() if document.period_month else None,
                        "kind": document.kind,
                        "remaining_total": str(state["remaining_total"]),
                    }
                )
        return Response(out)


class CashExpensePayrollPayoutsView(APIView):
    permission_classes = [IsAuthenticated, HasPayrollPayoutAccess]

    def get(self, request, pk):
        tenant = getattr(request, "tenant", None)
        rows = (
            PayrollPayout.objects.filter(tenant=tenant, cash_expense_id=pk)
            .select_related("document", "employee")
            .order_by("employee__full_name")
        )
        return Response(
            [
                {
                    "document_id": r.document_id,
                    "document_label": document_label(r.document),
                    "employee_id": r.employee_id,
                    "full_name": r.employee.full_name,
                    "amount": str(r.amount),
                }
                for r in rows
            ]
        )


class EmployeeListView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        qs = Employee.objects.filter(tenant=request.tenant).order_by("full_name")
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(full_name__icontains=search)
        return Response(EmployeeSerializer(qs[:500], many=True).data)


class EmployeeCreateView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def post(self, request):
        ser = EmployeeCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        employee, created = Employee.objects.get_or_create(
            tenant=request.tenant,
            full_name=ser.validated_data["full_name"],
            defaults={"created_by": request.user},
        )
        return Response(
            EmployeeSerializer(employee).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
