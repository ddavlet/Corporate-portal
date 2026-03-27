from datetime import date

from django.db import connection
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from apps.modules.requests.models import Approval, Request
from apps.modules.requests.serializers import ApprovalSerializer, PortalRequestDetailSerializer, PortalRequestSerializer
from apps.tenants.permissions import HasEffectiveModuleAccess
from apps.tenants.models import TenantUserRole


class PortalRequestViewSet(viewsets.ModelViewSet):
    """
    Placeholder CRUD for the Requests module.
    Replace/add fields once you provide the exact requests schema.
    """

    module_key = "requests"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = PortalRequestSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PortalRequestDetailSerializer
        return PortalRequestSerializer

    def _parse_date_query(self, key: str):
        raw = self.request.query_params.get(key)
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValidationError({key: "Use YYYY-MM-DD format."}) from exc

    def _has_role(self, tenant, role: str) -> bool:
        return TenantUserRole.objects.filter(
            tenant=tenant,
            user=self.request.user,
            role=role,
        ).exists()

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Request.objects.none()

        qs = Request.objects.filter(tenant=tenant)

        # Requesters can only see items they created.
        is_admin = self._has_role(tenant, TenantUserRole.ROLE_ADMIN)
        is_approver = self._has_role(tenant, TenantUserRole.ROLE_APPROVER)
        is_requester = self._has_role(tenant, TenantUserRole.ROLE_REQUESTER)

        if is_requester and not (is_admin or is_approver):
            qs = qs.filter(created_by=self.request.user)

        submitted_from = self._parse_date_query("submitted_from")
        submitted_to = self._parse_date_query("submitted_to")
        billing_from = self._parse_date_query("billing_from")
        billing_to = self._parse_date_query("billing_to")

        if submitted_from:
            qs = qs.filter(submitted_at__date__gte=submitted_from)
        if submitted_to:
            qs = qs.filter(submitted_at__date__lte=submitted_to)
        if billing_from:
            qs = qs.filter(billing_date__gte=billing_from)
        if billing_to:
            qs = qs.filter(billing_date__lte=billing_to)

        if self.action == "retrieve":
            if "approvals" in connection.introspection.table_names():
                qs = qs.prefetch_related("approvals", "approvals__approver_user")
            return qs

        return qs.order_by("-submitted_at")

    def perform_create(self, serializer):
        tenant = self.request.tenant
        serializer.save(tenant=tenant, created_by=self.request.user)

    @action(detail=True, methods=["get", "post"], url_path="approvals")
    def approvals(self, request, pk=None):
        request_obj = self.get_object()

        if Approval._meta.db_table not in connection.introspection.table_names():
            raise ValidationError({"approvals": "Approvals table is not available yet. Apply migrations first."})

        queryset = Approval.objects.filter(request=request_obj).select_related("approver_user").order_by("step", "id")

        if request.method == "GET":
            return Response(ApprovalSerializer(queryset, many=True).data)

        can_manage = self._has_role(request_obj.tenant, TenantUserRole.ROLE_ADMIN) or self._has_role(
            request_obj.tenant, TenantUserRole.ROLE_APPROVER
        )
        if not can_manage:
            raise PermissionDenied("Only admins or approvers can add approvals.")

        serializer = ApprovalSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(request=request_obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

