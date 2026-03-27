from datetime import date
import os

from django.db import connection
from django.db import IntegrityError
from django.db import transaction
import requests
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.modules.requests.models import (
    Approval,
    Request,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestFormPaymentTypeVendor,
    RequestPaymentPurposeConfig,
    Vendor,
)
from apps.modules.requests.serializers import (
    ApprovalSerializer,
    PortalRequestDetailSerializer,
    PortalRequestSerializer,
    RequestFormConfigPayloadSerializer,
    build_request_form_config_response,
)
from apps.tenants.permissions import HasEffectiveModuleAccess, IsTenantAdmin
from apps.tenants.models import TenantMembership, TenantUserRole


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

    @action(detail=False, methods=["post"], url_path="upsert")
    def upsert(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        incoming_id = request.data.get("id")
        if incoming_id in (None, ""):
            serializer = PortalRequestSerializer(data=request.data, context={"request": request})
            serializer.is_valid(raise_exception=True)
            serializer.save(tenant=tenant, created_by=request.user)
            return Response({"action": "created", "request": serializer.data}, status=status.HTTP_201_CREATED)

        try:
            normalized_id = int(incoming_id)
        except (TypeError, ValueError):
            raise ValidationError({"id": "ID must be an integer."})

        instance = Request.objects.filter(tenant=tenant, id=normalized_id).first()
        if instance:
            serializer = PortalRequestSerializer(instance=instance, data=request.data, partial=True, context={"request": request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response({"action": "updated", "request": serializer.data}, status=status.HTTP_200_OK)

        if Request.objects.filter(id=normalized_id).exists():
            raise ValidationError({"id": "This ID already exists in another tenant."})

        serializer = PortalRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(id=normalized_id, tenant=tenant, created_by=request.user)
        except IntegrityError as exc:
            raise ValidationError({"id": "Could not create request with this ID."}) from exc
        return Response({"action": "created", "request": serializer.data}, status=status.HTTP_201_CREATED)

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


class FileGatewayView(APIView):
    """
    Proxies file fetch through backend with N8N token from environment.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw_path = request.query_params.get("path", "").strip()
        if not raw_path:
            raise ValidationError({"path": "Query param 'path' is required."})
        if not (raw_path.startswith("http://") or raw_path.startswith("https://")):
            raise ValidationError({"path": "Path must be an absolute URL."})

        token = os.getenv("N8N_TOKEN", "").strip()
        if not token:
            return Response({"detail": "N8N_TOKEN is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            upstream = requests.get(
                raw_path,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
                stream=True,
            )
        except requests.RequestException:
            return Response({"detail": "Could not fetch file from upstream."}, status=status.HTTP_502_BAD_GATEWAY)

        content_type = upstream.headers.get("Content-Type", "application/octet-stream")
        content_disposition = upstream.headers.get("Content-Disposition")
        content_length = upstream.headers.get("Content-Length")

        resp = Response(upstream.content, status=upstream.status_code, content_type=content_type)
        if content_disposition:
            resp["Content-Disposition"] = content_disposition
        if content_length:
            resp["Content-Length"] = content_length
        return resp


class RequestFormConfigView(APIView):
    module_key = "requests"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess, IsTenantAdmin]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})
        return Response(build_request_form_config_response(tenant=tenant))

    def put(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        payload = RequestFormConfigPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        payment_types = payload.validated_data.get("payment_types", [])

        with transaction.atomic():
            cfg, _created = RequestFormConfig.objects.select_for_update().get_or_create(
                tenant=tenant,
                defaults={"updated_by": request.user},
            )
            cfg.updated_by = request.user
            cfg.save(update_fields=["updated_by", "updated_at"])

            # Upsert payment type configs, and replace nested collections.
            existing_pt = {
                row.payment_type: row
                for row in RequestFormPaymentTypeConfig.objects.filter(config=cfg)
            }
            seen_types: set[str] = set()

            for item in payment_types:
                pt = item["payment_type"]
                seen_types.add(pt)
                pt_cfg = existing_pt.get(pt)
                if not pt_cfg:
                    pt_cfg = RequestFormPaymentTypeConfig.objects.create(
                        config=cfg,
                        payment_type=pt,
                        is_enabled=bool(item.get("is_enabled", True)),
                    )
                else:
                    pt_cfg.is_enabled = bool(item.get("is_enabled", True))
                    pt_cfg.save(update_fields=["is_enabled"])

                # Replace requesters
                RequestFormPaymentTypeRequester.objects.filter(payment_type_config=pt_cfg).delete()
                requester_ids = list(item.get("requester_ids") or [])
                if requester_ids:
                    # Only allow active members with requester role.
                    allowed_requester_ids = set(
                        TenantUserRole.objects.filter(
                            tenant=tenant,
                            role=TenantUserRole.ROLE_REQUESTER,
                            user_id__in=requester_ids,
                        ).values_list("user_id", flat=True)
                    )
                    active_member_ids = set(
                        TenantMembership.objects.filter(
                            tenant=tenant,
                            is_active=True,
                            user_id__in=allowed_requester_ids,
                        ).values_list("user_id", flat=True)
                    )
                    rows = [
                        RequestFormPaymentTypeRequester(payment_type_config=pt_cfg, user_id=user_id)
                        for user_id in sorted(active_member_ids)
                    ]
                    if rows:
                        RequestFormPaymentTypeRequester.objects.bulk_create(rows)

                # Replace vendors (tenant-scoped)
                RequestFormPaymentTypeVendor.objects.filter(payment_type_config=pt_cfg).delete()
                vendor_ids = list(item.get("vendor_ids") or [])
                if vendor_ids:
                    valid_vendor_ids = set(
                        Vendor.objects.filter(tenant=tenant, id__in=vendor_ids).values_list("id", flat=True)
                    )
                    rows = [
                        RequestFormPaymentTypeVendor(payment_type_config=pt_cfg, vendor_id=vendor_id)
                        for vendor_id in sorted(valid_vendor_ids)
                    ]
                    if rows:
                        RequestFormPaymentTypeVendor.objects.bulk_create(rows)

                # Replace payment purposes
                RequestPaymentPurposeConfig.objects.filter(payment_type_config=pt_cfg).delete()
                purpose_items = list(item.get("payment_purposes") or [])
                purpose_rows: list[RequestPaymentPurposeConfig] = []
                for p in purpose_items:
                    name = str(p.get("name") or "").strip()
                    if not name:
                        continue
                    purpose_rows.append(
                        RequestPaymentPurposeConfig(
                            payment_type_config=pt_cfg,
                            name=name,
                            category=str(p.get("category") or "").strip(),
                            is_active=bool(p.get("is_active", True)),
                        )
                    )
                if purpose_rows:
                    RequestPaymentPurposeConfig.objects.bulk_create(purpose_rows)

            # If an admin removed a payment type from payload, disable it (do not delete).
            for pt, pt_cfg in existing_pt.items():
                if pt not in seen_types and pt_cfg.is_enabled:
                    pt_cfg.is_enabled = False
                    pt_cfg.save(update_fields=["is_enabled"])

        return Response(build_request_form_config_response(tenant=tenant))


class RequestFormOptionsView(APIView):
    module_key = "requests"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        cfg = RequestFormConfig.objects.filter(tenant=tenant).first()
        if not cfg:
            return Response({"payment_types": []})

        pt_qs = (
            RequestFormPaymentTypeConfig.objects.filter(config=cfg, is_enabled=True)
            .prefetch_related("allowed_requesters", "allowed_vendors", "payment_purposes")
            .order_by("payment_type")
        )
        return Response(
            {
                "payment_types": [
                    {
                        "payment_type": pt.payment_type,
                        "requester_ids": list(pt.allowed_requesters.values_list("user_id", flat=True)),
                        "vendor_ids": list(pt.allowed_vendors.values_list("vendor_id", flat=True)),
                        "payment_purposes": [
                            {"name": p.name, "category": p.category}
                            for p in pt.payment_purposes.filter(is_active=True).order_by("name", "id")
                        ],
                    }
                    for pt in pt_qs
                ]
            }
        )

