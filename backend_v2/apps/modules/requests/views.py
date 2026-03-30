from datetime import date
import logging
import mimetypes
import os

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import connection
from django.db import transaction
from django.db.models import Q
from django.core.files.storage import default_storage
from django.http import FileResponse
from django.utils import timezone
import requests
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework import serializers
from rest_framework.views import APIView

from apps.modules.requests.models import (
    Approval,
    Request,
    UserRequestApproval,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestFormPaymentTypeVendor,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepConfig,
    RequestApprovalStepApproverConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.vendors.models import Vendor
from apps.modules.requests.serializers import (
    ApprovalSerializer,
    PortalRequestDetailSerializer,
    PortalRequestSerializer,
    MyApprovalsRequestSummarySerializer,
    UserRequestApprovalStepSerializer,
    RequestFormConfigPayloadSerializer,
    build_request_form_config_response,
    payment_type_to_vendor_kind,
    RequestApprovalConfigPayloadSerializer,
    build_request_approval_config_response,
)

from apps.tenants.permissions import HasEffectiveModuleAccess, IsTenantAdmin
from apps.tenants.models import TenantMembership, TenantUserRole

User = get_user_model()


def _requester_candidates_for_options(tenant) -> list[dict]:
    requester_user_ids = list(
        TenantUserRole.objects.filter(
            tenant=tenant,
            role=TenantUserRole.ROLE_REQUESTER,
        ).values_list("user_id", flat=True)
    )
    active_ids = TenantMembership.objects.filter(
        tenant=tenant, is_active=True, user_id__in=requester_user_ids
    ).values_list("user_id", flat=True)
    return [
        {"id": u.id, "username": u.username}
        for u in User.objects.filter(id__in=active_ids).order_by("username")
    ]


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

        vendor_search = (self.request.query_params.get("vendor_search") or "").strip()
        if vendor_search:
            qs = qs.filter(
                Q(vendor_ref__name__icontains=vendor_search) | Q(vendor__icontains=vendor_search)
            )

        if self.action == "retrieve":
            if "approvals" in connection.introspection.table_names():
                qs = qs.prefetch_related("approvals", "approvals__approver_user")
            return qs

        return qs.order_by("-submitted_at")

    def perform_create(self, serializer):
        tenant = self.request.tenant
        approvals_payload: list[dict] = []
        obj: Request | None = None

        with transaction.atomic():
            obj = serializer.save(tenant=tenant, created_by=self.request.user)

            cfg = RequestApprovalConfig.objects.filter(tenant=tenant).first()
            if cfg:
                pt_cfg = cfg.payment_types.filter(payment_type=obj.payment_type, is_enabled=True).first()
                if pt_cfg:
                    step_cfgs = list(
                        pt_cfg.steps.filter(is_enabled=True)
                        .order_by("step", "id")
                        .prefetch_related("approvers__approver_user")
                    )

                    approver_ids: set[int] = set()
                    for step_cfg in step_cfgs:
                        approver_ids.update(
                            step_cfg.approvers.values_list("approver_user_id", flat=True).distinct()
                        )
                    active_approver_ids = set(
                        TenantMembership.objects.filter(
                            tenant=tenant, is_active=True, user_id__in=approver_ids
                        ).values_list("user_id", flat=True)
                    )

                    approval_rows: list[Approval] = []
                    for step_cfg in step_cfgs:
                        approvers = step_cfg.approvers.all()
                        for row in approvers:
                            if row.approver_user_id not in active_approver_ids:
                                continue
                            approval_rows.append(
                                Approval(
                                    request=obj,
                                    approver_user=row.approver_user,
                                    approver_tg_id=row.approver_user.telegram_chat_id,
                                    approver_tg_from_id=row.approver_user.telegram_from_id,
                                    message_id=None,
                                    message_sent=False,
                                    step=step_cfg.step,
                                    step_type=step_cfg.step_type,
                                    decision=Approval.DECISION_PENDING,
                                    comment=None,
                                    decided_at=None,
                                )
                            )

                    if approval_rows:
                        Approval.objects.bulk_create(approval_rows)
                        approvals_payload = [
                            {
                                "step": row.step,
                                "step_type": row.step_type,
                                "approver_user_id": row.approver_user_id,
                                "approver_tg_from_id": row.approver_user.telegram_from_id,
                                "decision": row.decision,
                            }
                            for row in approval_rows
                        ]

        # Notify n8n about created request and approvals list.
        n8n_token = getattr(settings, "N8N_TOKEN", "").strip()
        if not n8n_token or not getattr(tenant, "subdomain", None):
            return

        try:
            n8n_path = getattr(settings, "N8N_INTEGRATION_URL_PATH", "n8n").strip().strip("/")
            base_url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}"
            url = f"{base_url}/{n8n_path}/new_request"

            request_payload = {
                "id": obj.id if obj else None,
                "tenant_subdomain": tenant.subdomain,
                "payment_type": obj.payment_type if obj else None,
                "requester_user_id": obj.requester_id if obj else None,
            }

            payload = {"request": request_payload, "approvals": approvals_payload}
            resp = requests.post(
                url,
                json=payload,
                headers={"X-N8N-Token": n8n_token},
                timeout=10,
            )
            if resp.status_code >= 400:
                logging.getLogger(__name__).warning(
                    "n8n webhook returned HTTP %s for request id=%s",
                    resp.status_code,
                    obj.id if obj else None,
                )
        except Exception:
            logging.getLogger(__name__).exception("Failed to notify n8n for request id=%s", obj.id if obj else None)

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

    class ApprovalDecisionPayloadSerializer(serializers.Serializer):
        step = serializers.IntegerField(min_value=1)
        decision = serializers.ChoiceField(
            choices=[Approval.DECISION_APPROVED, Approval.DECISION_REJECTED]
        )
        comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    @action(detail=True, methods=["post"], url_path="approvals/decision")
    def approvals_decision(self, request, pk=None):
        """
        Update existing approval decision for current approver.

        This endpoint is intentionally "decision-only":
        it updates the existing `Approval` row instead of creating a new one (to avoid unique constraint errors).
        """
        request_obj = self.get_object()

        can_manage = self._has_role(request_obj.tenant, TenantUserRole.ROLE_ADMIN) or self._has_role(
            request_obj.tenant, TenantUserRole.ROLE_APPROVER
        )
        if not can_manage:
            raise PermissionDenied("Only admins or approvers can set approval decisions.")

        payload = self.ApprovalDecisionPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        step = payload.validated_data["step"]
        decision = payload.validated_data["decision"]
        comment = payload.validated_data.get("comment")
        if comment is not None and isinstance(comment, str):
            comment = comment.strip() or None

        approval = (
            Approval.objects.filter(
                request=request_obj,
                approver_user=request.user,
                step=step,
            )
            .select_related("approver_user")
            .first()
        )

        if not approval:
            return Response(
                {"detail": "Approval row not found for this step and approver."},
                status=status.HTTP_404_NOT_FOUND,
            )

        approval.decision = decision
        approval.comment = comment
        approval.decided_at = timezone.now()
        approval.save(update_fields=["decision", "comment", "decided_at"])

        ser = ApprovalSerializer(approval, context={"request": request})
        return Response(ser.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="file-upload")
    def file_upload(self, request, pk=None):
        """
        Telegram/Web client multipart upload.

        Stores file into Django filesystem storage under:
          requests/<tenant_id>/<request_id>/<filename>
        and updates `Request.file_link`.
        """
        request_obj = self.get_object()

        # For safety and UX: only allow attaching files to drafts.
        if request_obj.status != Request.STATUS_DRAFT:
            raise ValidationError({"detail": "Files can be attached only to DRAFT requests."})

        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Multipart field `file` is required."})

        tenant_id = request_obj.tenant_id
        req_id = request_obj.id
        if not tenant_id or not req_id:
            raise ValidationError({"detail": "Cannot resolve tenant_id/request_id for storage."})

        filename = os.path.basename(upload.name or "file") or "file"
        filename = filename.replace("\x00", "").replace("/", "_").replace("\\", "_")
        filename = filename.strip() or "file"

        storage_rel_path = f"requests/{tenant_id}/{req_id}/{filename}"
        saved_name = default_storage.save(storage_rel_path, upload)

        request_obj.file_link = saved_name
        request_obj.save(update_fields=["file_link"])

        return Response({"file_link": saved_name}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="my-approvals")
    def my_approvals(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response([])

        queryset = (
            UserRequestApproval.objects.filter(request__tenant=tenant, approver_user=request.user)
            .select_related("request", "request__requester")
            .order_by("request_id", "step", "id")
        )

        grouped: dict[int, dict] = {}
        for row in queryset:
            rid = row.request_id
            if rid not in grouped:
                grouped[rid] = {
                    "request": MyApprovalsRequestSummarySerializer(row.request, context={"request": request}).data,
                    "approvals": [],
                }

            grouped[rid]["approvals"].append(UserRequestApprovalStepSerializer(row).data)

        return Response(list(grouped.values()))


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


def _sanitize_storage_relative_path(raw_path: str) -> str:
    """
    Convert the `path` query param into a Django storage-relative path.

    Security rules:
    - must not be absolute and must not contain `..`
    - must be under `requests/` prefix
    """
    path = (raw_path or "").strip()
    if not path:
        raise ValidationError({"path": "Query param 'path' is required."})

    # Reject absolute paths / weird characters.
    if path.startswith(("/", "\\")) or "\x00" in path:
        raise ValidationError({"path": "Invalid path."})

    # Normalize separators and remove leading './'.
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]

    segments = [seg for seg in path.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in segments):
        raise ValidationError({"path": "Path traversal is not allowed."})

    if not path.startswith("requests/"):
        raise ValidationError({"path": "Path must be under 'requests/'."})

    return path


class FileDownloadView(APIView):
    """
    Auth-protected file download endpoint for files stored inside Django filesystem storage.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rel_path = _sanitize_storage_relative_path(request.query_params.get("path", ""))

        if not default_storage.exists(rel_path):
            return Response({"detail": "File not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            fh = default_storage.open(rel_path, mode="rb")
        except Exception:
            return Response({"detail": "File not available."}, status=status.HTTP_404_NOT_FOUND)

        filename = os.path.basename(rel_path)
        content_type, _ = mimetypes.guess_type(filename)
        content_type = content_type or "application/octet-stream"

        # Stream the file without loading it into memory.
        return FileResponse(
            fh,
            as_attachment=True,
            filename=filename,
            content_type=content_type,
        )


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

                purpose_items = list(item.get("payment_purposes") or [])
                purpose_names = {
                    str(p.get("name") or "").strip()
                    for p in purpose_items
                    if str(p.get("name") or "").strip()
                }
                dp = str(item.get("default_payment_purpose") or "").strip()
                if dp and dp not in purpose_names:
                    raise ValidationError(
                        {
                            "payment_types": f"Значение по умолчанию «назначение платежа» ({dp!r}) должно "
                            f"совпадать с одним из назначений для типа «{pt}»."
                        }
                    )

                requested_vendor_ids = list(item.get("vendor_ids") or [])
                valid_vendor_ids: set[int] = set()
                if requested_vendor_ids:
                    valid_vendor_ids = set(
                        Vendor.objects.filter(
                            tenant=tenant, id__in=requested_vendor_ids
                        ).values_list("id", flat=True)
                    )

                dvid = item.get("default_vendor_id")
                if dvid:
                    dv = Vendor.objects.filter(tenant=tenant, id=dvid).first()
                    if not dv or dv.kind != payment_type_to_vendor_kind(pt):
                        raise ValidationError(
                            {
                                "payment_types": f"Поставщик по умолчанию недопустим для типа «{pt}» "
                                f"(тенант или вид оплаты)."
                            }
                        )
                    if valid_vendor_ids and dvid not in valid_vendor_ids:
                        raise ValidationError(
                            {
                                "payment_types": f"Поставщик по умолчанию должен входить в список поставщиков для «{pt}»."
                            }
                        )

                pt_cfg.default_title = str(item.get("default_title") or "")[:200]
                pt_cfg.default_description = str(item.get("default_description") or "")
                pt_cfg.default_amount = item.get("default_amount")
                pt_cfg.default_currency = item.get("default_currency", Request.CURRENCY_UZS)
                pt_cfg.default_urgency = item.get("default_urgency", Request.URGENCY_NORMAL)
                pt_cfg.default_billing_days_offset = int(item.get("default_billing_days_offset", 0))
                pt_cfg.default_payment_purpose = dp
                pt_cfg.default_vendor_id = dvid if dvid else None
                pt_cfg.save(
                    update_fields=[
                        "is_enabled",
                        "default_title",
                        "default_description",
                        "default_amount",
                        "default_currency",
                        "default_urgency",
                        "default_billing_days_offset",
                        "default_payment_purpose",
                        "default_vendor",
                    ]
                )

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

        is_tenant_admin = TenantUserRole.objects.filter(
            tenant=tenant,
            user=request.user,
            role=TenantUserRole.ROLE_ADMIN,
        ).exists()
        requester_candidates = _requester_candidates_for_options(tenant)

        cfg = RequestFormConfig.objects.filter(tenant=tenant).first()
        if not cfg:
            return Response(
                {
                    "is_tenant_admin": is_tenant_admin,
                    "requester_candidates": requester_candidates,
                    "payment_types": [],
                }
            )

        pt_qs = (
            RequestFormPaymentTypeConfig.objects.filter(config=cfg, is_enabled=True)
            .prefetch_related("allowed_requesters", "allowed_vendors", "payment_purposes")
            .order_by("payment_type")
        )
        def requesters_payload(pt_cfg):
            # Только пользователи, явно выбранные в настройках формы для этого типа оплаты.
            # Пустой список в настройках → пустой список в форме (без подстановки «все заявители»).
            rids = list(pt_cfg.allowed_requesters.values_list("user_id", flat=True))
            if not rids:
                return []
            qs_users = User.objects.filter(id__in=rids).order_by("username")
            return [{"id": u.id, "username": u.username} for u in qs_users]

        def form_defaults(pt_cfg: RequestFormPaymentTypeConfig) -> dict:
            amt = pt_cfg.default_amount
            return {
                "title": pt_cfg.default_title,
                "description": pt_cfg.default_description,
                "amount": str(amt) if amt is not None else None,
                "currency": pt_cfg.default_currency,
                "urgency": pt_cfg.default_urgency,
                "billing_days_offset": pt_cfg.default_billing_days_offset,
                "payment_purpose": pt_cfg.default_payment_purpose or None,
                "vendor_ref": pt_cfg.default_vendor_id,
            }

        return Response(
            {
                "is_tenant_admin": is_tenant_admin,
                "requester_candidates": requester_candidates,
                "payment_types": [
                    {
                        "payment_type": pt.payment_type,
                        "requester_ids": list(pt.allowed_requesters.values_list("user_id", flat=True)),
                        "requesters": requesters_payload(pt),
                        "vendor_ids": list(pt.allowed_vendors.values_list("vendor_id", flat=True)),
                        "payment_purposes": [
                            {"name": p.name, "category": p.category}
                            for p in pt.payment_purposes.filter(is_active=True).order_by("name", "id")
                        ],
                        "defaults": form_defaults(pt),
                    }
                    for pt in pt_qs
                ],
            }
        )


class RequestApprovalConfigView(APIView):
    module_key = "requests"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess, IsTenantAdmin]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})
        return Response(build_request_approval_config_response(tenant=tenant))

    def put(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        payload = RequestApprovalConfigPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        payment_types = payload.validated_data.get("payment_types", [])

        # For each step approver list, validate user is active member and has role "approver".
        # Also keep IDs unique to avoid duplicate approver rows.
        valid_role_user_ids = set(
            TenantUserRole.objects.filter(
                tenant=tenant,
                role=TenantUserRole.ROLE_APPROVER,
            ).values_list("user_id", flat=True)
        )
        active_member_ids = set(
            TenantMembership.objects.filter(tenant=tenant, is_active=True, user_id__in=valid_role_user_ids).values_list(
                "user_id", flat=True
            )
        )

        with transaction.atomic():
            cfg, _created = RequestApprovalConfig.objects.select_for_update().get_or_create(
                tenant=tenant, defaults={"updated_by": request.user}
            )
            cfg.updated_by = request.user
            cfg.save(update_fields=["updated_by", "updated_at"])

            existing_pt = {
                row.payment_type: row
                for row in RequestApprovalPaymentTypeConfig.objects.filter(config=cfg)
            }
            seen_types: set[str] = set()

            for item in payment_types:
                pt = item["payment_type"]
                seen_types.add(pt)

                pt_cfg = existing_pt.get(pt)
                if not pt_cfg:
                    pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
                        config=cfg,
                        payment_type=pt,
                        is_enabled=bool(item.get("is_enabled", True)),
                    )
                else:
                    pt_cfg.is_enabled = bool(item.get("is_enabled", True))

                pt_cfg.save(update_fields=["is_enabled"])

                # Replace step configs for this payment type.
                RequestApprovalStepConfig.objects.filter(payment_type_config=pt_cfg).delete()

                steps = list(item.get("steps") or [])
                step_rows: list[RequestApprovalStepConfig] = []
                for step_item in steps:
                    step_no = int(step_item["step"])
                    step_cfg = RequestApprovalStepConfig(
                        payment_type_config=pt_cfg,
                        step=step_no,
                        step_type=step_item["step_type"],
                        is_enabled=bool(step_item.get("is_enabled", True)),
                    )
                    step_rows.append(step_cfg)

                if step_rows:
                    RequestApprovalStepConfig.objects.bulk_create(step_rows)

                # Re-fetch created step configs ordered by step_no.
                created_steps = (
                    RequestApprovalStepConfig.objects.filter(payment_type_config=pt_cfg)
                    .order_by("step", "id")
                    .all()
                )

                for step_cfg in created_steps:
                    # Find corresponding payload step.
                    matched = next((s for s in steps if int(s["step"]) == step_cfg.step), None)
                    if not matched:
                        continue

                    raw_ids = list(matched.get("approver_user_ids") or [])
                    unique_ids = sorted(set(int(x) for x in raw_ids))
                    invalid = [uid for uid in unique_ids if uid not in active_member_ids]
                    if invalid:
                        raise ValidationError(
                            {"approver_user_ids": f"Invalid approver users for step {step_cfg.step}: {invalid}."}
                        )

                    rows = [
                        RequestApprovalStepApproverConfig(step_config=step_cfg, approver_user_id=uid)
                        for uid in unique_ids
                    ]
                    if rows:
                        RequestApprovalStepApproverConfig.objects.bulk_create(rows)

            # Disable payment types that are missing from payload.
            for pt, pt_cfg in existing_pt.items():
                if pt not in seen_types and pt_cfg.is_enabled:
                    pt_cfg.is_enabled = False
                    pt_cfg.save(update_fields=["is_enabled"])

        return Response(build_request_approval_config_response(tenant=tenant))

