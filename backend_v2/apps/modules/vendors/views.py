from django.db.models import Q
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.common.pagination import PortalCursorPagination
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.vendors.models import Vendor
from apps.modules.vendors.serializers import VendorSerializer
from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import HasEffectiveModuleAccess


class CanWriteVendorDirectory(BasePermission):
    def has_permission(self, request, view):
        tenant = getattr(request, "tenant", None)
        if not tenant or not request.user or not request.user.is_authenticated:
            return False
        return TenantUserRole.objects.filter(
            tenant=tenant,
            user=request.user,
            role__in=(
                TenantUserRole.ROLE_ADMIN,
                TenantUserRole.ROLE_DIRECTOR,
                TenantUserRole.ROLE_CASHIER,
                TenantUserRole.ROLE_ACCOUNTANT,
            ),
        ).exists()


class VendorCursorPagination(PortalCursorPagination):
    ordering = "name,id"


class VendorViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "vendors"
    serializer_class = VendorSerializer
    pagination_class = VendorCursorPagination
    ordering_fields = ["name", "id", "inn"]
    ordering = ["name", "id"]

    def get_permissions(self):
        base = [IsAuthenticated(), HasEffectiveModuleAccess()]
        if self.action in ("create", "update", "partial_update", "destroy"):
            return base + [CanWriteVendorDirectory()]
        return base

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Vendor.objects.none()
        qs = Vendor.objects.filter(tenant=tenant).order_by("name", "id")
        kind = (self.request.query_params.get("kind") or "").strip().lower()
        if kind in (Vendor.KIND_CASH, Vendor.KIND_TRANSFER):
            qs = qs.filter(kind=kind)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(inn__icontains=search))
        return qs

    def perform_create(self, serializer):
        tenant = self.request.tenant
        serializer.save(tenant=tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.tenant_id != self.request.tenant.id:
            raise PermissionDenied("Tenant mismatch.")
        serializer.save()
