from django.utils import timezone

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.common.pagination import PortalCursorPagination
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.budgets.models import Budget
from apps.modules.budgets.serializers import BudgetSerializer, _period_date_range
from apps.modules.requests.models import Request
from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import HasEffectiveModuleAccess


class CanManageBudgets(BasePermission):
    """Create / update / delete requires admin or director."""

    def has_permission(self, request, view):
        tenant = getattr(request, "tenant", None)
        if not tenant or not request.user or not request.user.is_authenticated:
            return False
        return TenantUserRole.objects.filter(
            tenant=tenant,
            user=request.user,
            role__in=(TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR),
        ).exists()


def _parse_period_params(query_params):
    today = timezone.localdate()
    try:
        year = int(query_params.get("year") or today.year)
    except (ValueError, TypeError):
        year = today.year
    try:
        period_index = int(query_params.get("period") or today.month)
    except (ValueError, TypeError):
        period_index = today.month
    return year, period_index


class BudgetCursorPagination(PortalCursorPagination):
    ordering = "name"


class BudgetViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "budgets"
    serializer_class = BudgetSerializer
    pagination_class = BudgetCursorPagination
    ordering_fields = ["name", "id", "is_active"]
    ordering = ["name", "id"]

    def get_permissions(self):
        base = [IsAuthenticated(), HasEffectiveModuleAccess()]
        if self.action in ("create", "update", "partial_update", "destroy"):
            return base + [CanManageBudgets()]
        return base

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        year, period_index = _parse_period_params(self.request.query_params)
        ctx["year"] = year
        ctx["period_index"] = period_index
        return ctx

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Budget.objects.none()
        qs = Budget.objects.filter(tenant=tenant).select_related("category").order_by("name", "id")
        category = (self.request.query_params.get("category") or "").strip()
        if category:
            qs = qs.filter(category__name=category)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("1", "true", "yes"))
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.tenant_id != self.request.tenant.id:
            raise PermissionDenied("Tenant mismatch.")
        serializer.save()

    @action(detail=False, methods=["get"], url_path="categories")
    def categories(self, request):
        """Return active RequestCategories for this tenant for use in the create/edit form."""
        from apps.modules.requests.models import RequestCategory
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response([])
        qs = RequestCategory.objects.filter(tenant=tenant, is_active=True).order_by("name").values("id", "name")
        return Response(list(qs))

    @action(detail=True, methods=["get"], url_path="spend-detail")
    def spend_detail(self, request, pk=None):
        """Return the individual requests counted toward this budget's spend."""
        budget = self.get_object()
        year, period_index = _parse_period_params(request.query_params)
        start, end = _period_date_range(budget.period_type, year, period_index)
        qs = Request.objects.filter(
            tenant=budget.tenant,
            category=budget.category.name,
            currency=budget.currency,
            status__in=[Request.STATUS_APPROVED, Request.STATUS_PAYED],
            billing_date__gte=start,
            billing_date__lt=end,
        ).order_by("-billing_date").values(
            "id", "title", "amount", "currency", "category",
            "status", "billing_date", "payment_type",
        )
        return Response({"results": list(qs)})
