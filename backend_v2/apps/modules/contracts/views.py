import mimetypes
import os

from django.core.files.storage import default_storage
from django.http import FileResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from django.db.models import Q

from apps.common.pagination import PortalCursorPagination
from apps.common.query_params import parse_date_query
from apps.common.viewsets import PortalListViewSetMixin
from apps.modules.contracts.models import Contract
from apps.modules.contracts.serializers import ContractSerializer
from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import HasEffectiveModuleAccess


class CanManageContracts(BasePermission):
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


class ContractCursorPagination(PortalCursorPagination):
    ordering = "-date_from,-id"


class ContractViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "contracts"
    serializer_class = ContractSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = ContractCursorPagination
    ordering_fields = ["date_from", "date_to", "contract_number", "id", "amount"]
    ordering = ["-date_from", "-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Contract.objects.none()
        qs = Contract.objects.filter(tenant=tenant).select_related("vendor")
        vendor_id = (self.request.query_params.get("vendor") or "").strip()
        if vendor_id.isdigit():
            qs = qs.filter(vendor_id=int(vendor_id))
            qs = qs.exclude(contract_status=Contract.STATUS_REFUSED)
        status_raw = (self.request.query_params.get("status") or "").strip()
        if status_raw:
            qs = qs.filter(contract_status=status_raw)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(contract_number__icontains=search) | Q(vendor__name__icontains=search))
        date_from = parse_date_query(self.request, "date_from")
        date_to = parse_date_query(self.request, "date_to")
        if date_from:
            qs = qs.filter(date_from__gte=date_from)
        if date_to:
            qs = qs.filter(date_from__lte=date_to)
        return qs.order_by("-date_from", "-id")

    def get_permissions(self):
        base = [IsAuthenticated(), HasEffectiveModuleAccess()]
        if self.action in ("create", "update", "partial_update", "destroy"):
            return base + [CanManageContracts()]
        return base

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.tenant_id != self.request.tenant.id:
            raise PermissionDenied("Tenant mismatch.")
        serializer.save()

    @action(detail=True, methods=["get"], url_path="file")
    def download_file(self, request, pk=None):
        obj = self.get_object()
        if not obj.contract_file:
            return Response({"detail": "Файл не приложен."}, status=404)
        rel_path = obj.contract_file.name
        if not rel_path or not default_storage.exists(rel_path):
            return Response({"detail": "Файл не найден."}, status=404)
        try:
            fh = default_storage.open(rel_path, mode="rb")
        except OSError:
            return Response({"detail": "Файл недоступен."}, status=404)
        filename = os.path.basename(rel_path)
        content_type, _ = mimetypes.guess_type(filename)
        content_type = content_type or "application/octet-stream"
        return FileResponse(fh, as_attachment=True, filename=filename, content_type=content_type)
