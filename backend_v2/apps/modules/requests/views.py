from datetime import date
import mimetypes
import os

from django.contrib.auth import get_user_model
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
    RequestCategory,
    AutoRequestTemplate,
)
from apps.modules.vendors.models import Vendor
from apps.modules.requests.serializers import (
    ApprovalSerializer,
    ApprovalFullContextSerializer,
    PortalRequestDetailSerializer,
    PortalRequestSerializer,
    MyApprovalsRequestSummarySerializer,
    UserRequestApprovalStepSerializer,
    RequestFormConfigPayloadSerializer,
    CreateTenantRequesterSerializer,
    build_request_form_config_response,
    payment_type_to_vendor_kind,
    RequestApprovalConfigPayloadSerializer,
    build_request_approval_config_response,
    AutoRequestConfigPayloadSerializer,
    build_auto_request_config_response,
    validate_auto_template_against_form_config,
)
from apps.modules.requests.expense_refs import try_resolve_request_expense_ref_id
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import (
    _recalculate_request_status,
    confirm_approval_by_id,
    lookup_approval_by_message_id,
    min_pending_approval_step,
    route_request_approvals,
)
from apps.modules.telegram_approvals.services import (
    current_pending_step_approvals_count,
    dispatch_pending_approvals,
    refresh_request_messages,
    resend_current_pending_step,
)
from apps.tenants.integration_settings import get_requests_gateway_settings

from apps.tenants.permissions import HasEffectiveModuleAccess, IsTenantAdmin
from apps.tenants.models import TenantMembership, TenantUserRole

User = get_user_model()


def _display_user_name(user) -> str:
    full = (getattr(user, "full_name", "") or "").strip()
    return full or user.username


def _ensure_app_user_for_auto_requests(tenant):
    """
    Системный пользователь `app` — заявитель создаваемых по расписанию заявок.
    Для каждого тенанта обеспечивается членство и роль заявителя (как у обычного requester).
    """
    app_user, created = User.objects.get_or_create(
        username="app",
        defaults={
            "full_name": "Система",
            "is_active": True,
        },
    )
    if created:
        app_user.set_unusable_password()
        app_user.save(update_fields=["password"])
    TenantMembership.objects.get_or_create(tenant=tenant, user=app_user, defaults={"is_active": True})
    TenantUserRole.objects.get_or_create(
        tenant=tenant, user=app_user, role=TenantUserRole.ROLE_REQUESTER, defaults={"step": 1}
    )
    return app_user



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
        {"id": u.id, "username": _display_user_name(u)}
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
        obj: Request | None = None

        with transaction.atomic():
            obj = serializer.save(tenant=tenant, created_by=self.request.user)
            n = create_approval_rows_for_request(obj)
            if n and obj and obj.status == Request.STATUS_DRAFT:
                _recalculate_request_status(obj)

        if obj is not None:
            route_request_approvals(request_obj=obj)

    def _user_can_patch_draft_request(self, user, request_obj: Request) -> bool:
        tenant = request_obj.tenant
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if self._has_role(tenant, TenantUserRole.ROLE_ADMIN):
            return True
        if request_obj.created_by_id == user.id:
            return True
        if request_obj.requester_id == user.id:
            return True
        return False

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        if instance.status != Request.STATUS_DRAFT:
            raise ValidationError({"detail": "Only DRAFT requests can be updated."})
        if not self._user_can_patch_draft_request(request.user, instance):
            raise PermissionDenied("You cannot edit this draft.")
        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
            context={**self.get_serializer_context(), "draft_save": True},
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        obj = serializer.instance
        route_request_approvals(request_obj=obj)

    @action(detail=True, methods=["post"], url_path="submit-for-approval")
    def submit_for_approval(self, request, pk=None):
        tenant = self.request.tenant
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})
        with transaction.atomic():
            request_obj = Request.objects.select_for_update().get(pk=pk, tenant=tenant)
            if request_obj.status != Request.STATUS_DRAFT:
                return Response(
                    {"detail": "Request already submitted for approval."},
                    status=status.HTTP_409_CONFLICT,
                )
            if Approval.objects.filter(request=request_obj).exists():
                return Response(
                    {"detail": "Request already has approvals."},
                    status=status.HTTP_409_CONFLICT,
                )
            if not self._user_can_patch_draft_request(request.user, request_obj):
                raise PermissionDenied("You cannot submit this draft.")
            serializer = self.get_serializer(
                request_obj,
                data=request.data or {},
                partial=True,
                context={**self.get_serializer_context(), "submit_for_approval": True},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            n = create_approval_rows_for_request(request_obj)
            if n and request_obj.status == Request.STATUS_DRAFT:
                _recalculate_request_status(request_obj)
        route_request_approvals(request_obj=request_obj)
        detail_qs = self.get_queryset().filter(pk=request_obj.pk)
        obj = detail_qs.get()
        return Response(
            PortalRequestDetailSerializer(obj, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

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
        request_obj.refresh_from_db()
        route_request_approvals(request_obj=request_obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    class ApprovalDecisionPayloadSerializer(serializers.Serializer):
        step = serializers.IntegerField(min_value=1)
        decision = serializers.ChoiceField(
            choices=[Approval.DECISION_APPROVED, Approval.DECISION_REJECTED]
        )
        comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class ApprovalConfirmPayloadSerializer(serializers.Serializer):
        approval_id = serializers.IntegerField(min_value=1)
        comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class PaymentWebAppConfirmPayloadSerializer(serializers.Serializer):
        approval_id = serializers.IntegerField(min_value=1)
        expense_id = serializers.CharField()

    class ApprovalResendPayloadSerializer(serializers.Serializer):
        idempotency_key = serializers.CharField(required=False, allow_blank=False, max_length=128)

    @action(detail=True, methods=["post"], url_path="approvals/resend")
    def approvals_resend(self, request, pk=None):
        request_obj = self.get_object()
        can_manage = self._has_role(request_obj.tenant, TenantUserRole.ROLE_ADMIN) or self._has_role(
            request_obj.tenant, TenantUserRole.ROLE_APPROVER
        )
        if not can_manage:
            raise PermissionDenied("Only admins or approvers can resend approvals.")
        payload = self.ApprovalResendPayloadSerializer(data=request.data or {})
        payload.is_valid(raise_exception=True)
        idempotency_key = payload.validated_data.get("idempotency_key")
        pending_current_step = current_pending_step_approvals_count(request_obj=request_obj)
        resent = resend_current_pending_step(request_obj=request_obj, idempotency_key=idempotency_key)
        route_request_approvals(request_obj=request_obj)
        return Response(
            {
                "resent": resent,
                "pending_current_step": pending_current_step,
            },
            status=status.HTTP_200_OK,
        )

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

        with transaction.atomic():
            locked_request = Request.objects.select_for_update().get(pk=request_obj.pk)
            approval = (
                Approval.objects.select_for_update()
                .filter(
                    request_id=locked_request.pk,
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

            active_step = min_pending_approval_step(request_id=locked_request.pk)
            if active_step is None or approval.step != active_step:
                raise ValidationError(
                    {
                        "detail": "Этот этап согласования ещё не активен. Сначала завершите предыдущие шаги.",
                    }
                )

            data = confirm_approval_by_id(
                tenant=locked_request.tenant,
                approval_id=approval.id,
                request_id=locked_request.id,
                approver_user_id=request.user.id,
                decision=decision,
                comment=comment,
            )

        return Response(
            ApprovalFullContextSerializer(data, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="approvals/confirm")
    def approvals_confirm(self, request, pk=None):
        payload = self.ApprovalConfirmPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        approval_id = payload.validated_data["approval_id"]
        comment = payload.validated_data.get("comment")
        if isinstance(comment, str):
            comment = comment.strip() or None

        request_obj = self.get_object()
        data = confirm_approval_by_id(
            tenant=request_obj.tenant,
            approval_id=approval_id,
            request_id=request_obj.id,
            approver_user_id=request.user.id,
            comment=comment,
        )
        return Response(
            ApprovalFullContextSerializer(data, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="approvals/by-message-id")
    def approvals_by_message_id(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        raw_message_id = (request.query_params.get("message_id") or "").strip()
        if not raw_message_id:
            raise ValidationError({"message_id": "This query param is required."})
        try:
            message_id = int(raw_message_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"message_id": "Must be an integer."}) from exc

        data = lookup_approval_by_message_id(tenant=tenant, message_id=message_id)
        return Response(
            ApprovalFullContextSerializer(data, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="approvals/payment-webapp/confirm")
    def approvals_payment_webapp_confirm(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        payload = self.PaymentWebAppConfirmPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        approval_id = payload.validated_data["approval_id"]
        expense_id = str(payload.validated_data["expense_id"] or "").strip()
        if not expense_id:
            raise ValidationError({"expense_id": "Expense id is required."})

        approval = (
            Approval.objects.select_related("request", "request__tenant")
            .filter(id=approval_id, request__tenant=tenant, approver_user=request.user)
            .first()
        )
        if approval is None:
            raise PermissionDenied("Approver is not assigned to this approval.")
        if approval.step_type != Approval.STEP_TYPE_PAYMENT:
            raise ValidationError({"approval_id": "Approval is not a payment step."})

        step_cfg = (
            RequestApprovalStepConfig.objects.filter(
                payment_type_config__config__tenant=tenant,
                payment_type_config__payment_type=approval.request.payment_type,
                step=approval.step,
                step_type=approval.step_type,
            )
            .order_by("id")
            .first()
        )
        if (
            step_cfg
            and step_cfg.payment_action_mode == RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK
        ):
            raise ValidationError({"approval_id": "Payment step is configured for callback mode."})

        request_obj = approval.request
        request_obj.expense_id = expense_id
        request_obj.expense_ref_id = try_resolve_request_expense_ref_id(
            tenant=tenant,
            payment_type=request_obj.payment_type,
            category=request_obj.category,
            expense_id_raw=expense_id,
            expense_year=request_obj.expense_year,
        )
        request_obj.save(update_fields=["expense_id", "expense_ref_id"])

        data = confirm_approval_by_id(
            tenant=tenant,
            approval_id=approval.id,
            request_id=request_obj.id,
            approver_user_id=request.user.id,
            decision=Approval.DECISION_APPROVED,
        )
        return Response(
            ApprovalFullContextSerializer(data, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

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

        token = get_requests_gateway_settings(tenant=getattr(request, "tenant", None)).bearer_token
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
        category_candidates_provided = "category_candidates" in payload.validated_data
        category_candidates = payload.validated_data.get("category_candidates", [])

        with transaction.atomic():
            if category_candidates_provided:
                requested_category_names = sorted(
                    {
                        str(raw_name).strip()
                        for raw_name in category_candidates
                        if str(raw_name).strip()
                    }
                )
                existing_categories = {
                    row.name: row for row in RequestCategory.objects.select_for_update().filter(tenant=tenant)
                }
                for category_name in requested_category_names:
                    row = existing_categories.get(category_name)
                    if row:
                        if not row.is_active:
                            row.is_active = True
                            row.save(update_fields=["is_active", "updated_at"])
                    else:
                        RequestCategory.objects.create(
                            tenant=tenant,
                            name=category_name,
                            is_active=True,
                        )

                for existing_name, existing_row in existing_categories.items():
                    if existing_name not in requested_category_names and existing_row.is_active:
                        existing_row.is_active = False
                        existing_row.save(update_fields=["is_active", "updated_at"])

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
                pt_cfg.default_company_payer = str(item.get("default_company_payer") or "")[:100]
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
                        "default_company_payer",
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


class RequestFormConfigRequestersView(APIView):
    module_key = "requests"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess, IsTenantAdmin]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})

        payload = CreateTenantRequesterSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        username = payload.validated_data["username"]
        full_name = payload.validated_data["full_name"]
        telegram_chat_id = payload.validated_data.get("telegram_chat_id")
        telegram_from_id = payload.validated_data.get("telegram_from_id")

        if User.objects.filter(username=username).exists():
            raise ValidationError(
                {"username": "A user with this username already exists."}
            )

        with transaction.atomic():
            user = User(username=username)
            user.set_unusable_password()
            user.full_name = full_name
            user.is_active = True
            if telegram_chat_id is not None:
                user.telegram_chat_id = telegram_chat_id
            if telegram_from_id is not None:
                user.telegram_from_id = telegram_from_id
            user.save()

            TenantMembership.objects.update_or_create(
                tenant=tenant,
                user=user,
                defaults={"is_active": True},
            )
            TenantUserRole.objects.update_or_create(
                tenant=tenant,
                user=user,
                role=TenantUserRole.ROLE_REQUESTER,
                defaults={"step": 1},
            )

        return Response(build_request_form_config_response(tenant=tenant), status=status.HTTP_200_OK)


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
            return [{"id": u.id, "username": _display_user_name(u)} for u in qs_users]

        def form_defaults(pt_cfg: RequestFormPaymentTypeConfig) -> dict:
            amt = pt_cfg.default_amount
            return {
                "title": pt_cfg.default_title,
                "company_payer": pt_cfg.default_company_payer,
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
        integration_settings = payload.validated_data.get("integration_settings", {})

        active_member_ids = set(
            TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
        )

        with transaction.atomic():
            cfg, _created = RequestApprovalConfig.objects.select_for_update().get_or_create(
                tenant=tenant, defaults={"updated_by": request.user}
            )
            cfg.updated_by = request.user
            for field in (
                "telegram_approvals_bridge_dispatch_url",
                "telegram_approvals_send_action",
                "telegram_approvals_edit_action",
                "telegram_approvals_draft_notification_action",
                "telegram_approvals_bridge_token",
                "telegram_approvals_message_template",
                "telegram_approvals_header_new_template",
                "telegram_approvals_header_step_approved_template",
                "telegram_approvals_header_fully_approved_template",
                "telegram_approvals_header_closed_template",
                "telegram_approvals_header_rejected_template",
                "telegram_approvals_subheader_payment_responsible_template",
                "telegram_approvals_subheader_rejected_by_template",
                "n8n_integration_token",
            ):
                if field in integration_settings:
                    setattr(cfg, field, integration_settings[field])
            cfg.save()

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
                RequestApprovalStepConfig.objects.filter(payment_type_config=pt_cfg).delete()

                steps = list(item.get("steps") or [])
                step_rows: list[RequestApprovalStepConfig] = []
                for step_item in steps:
                    step_cfg = RequestApprovalStepConfig(
                        payment_type_config=pt_cfg,
                        step=int(step_item["step"]),
                        step_type=step_item["step_type"],
                        is_enabled=bool(step_item.get("is_enabled", True)),
                        payment_action_mode=step_item.get(
                            "payment_action_mode",
                            RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK,
                        ),
                        payment_webapp_url=str(step_item.get("payment_webapp_url", "") or "").strip(),
                    )
                    step_rows.append(step_cfg)
                if step_rows:
                    RequestApprovalStepConfig.objects.bulk_create(step_rows)

                created_steps = (
                    RequestApprovalStepConfig.objects.filter(payment_type_config=pt_cfg)
                    .order_by("step", "id")
                    .all()
                )
                for step_cfg in created_steps:
                    matched = next((s for s in steps if int(s["step"]) == step_cfg.step), None)
                    if not matched:
                        continue
                    unique_ids = sorted(set(int(x) for x in list(matched.get("approver_user_ids") or [])))
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

            for pt, pt_cfg in existing_pt.items():
                if pt not in seen_types and pt_cfg.is_enabled:
                    pt_cfg.is_enabled = False
                    pt_cfg.save(update_fields=["is_enabled"])

        return Response(build_request_approval_config_response(tenant=tenant))


class AutoRequestConfigView(APIView):
    module_key = "requests"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess, IsTenantAdmin]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})
        return Response(build_auto_request_config_response(tenant=tenant))

    def put(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise ValidationError({"detail": "Unknown tenant."})
        payload = AutoRequestConfigPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        template_items = payload.validated_data.get("templates", [])
        _ensure_app_user_for_auto_requests(tenant)

        for idx, item in enumerate(template_items):
            try:
                validate_auto_template_against_form_config(tenant=tenant, item=item)
            except ValidationError as exc:
                d = exc.detail
                if isinstance(d, list) and d:
                    msg = str(d[0])
                elif isinstance(d, dict):
                    msg = str(next(iter(d.values())))
                else:
                    msg = str(d)
                raise ValidationError({"detail": f"Шаблон {idx + 1}: {msg}"}) from exc

        with transaction.atomic():
            existing = {row.id: row for row in AutoRequestTemplate.objects.select_for_update().filter(tenant=tenant)}
            seen_ids: set[int] = set()

            for item in template_items:
                row_id = item.get("id")
                requester_id = int(item["requester_id"])

                vendor_ref_id = item.get("vendor_ref_id")
                if vendor_ref_id and not Vendor.objects.filter(tenant=tenant, id=vendor_ref_id).exists():
                    raise ValidationError({"vendor_ref_id": "Vendor must belong to this tenant."})

                defaults = {
                    "is_enabled": bool(item.get("is_enabled", False)),
                    "name": str(item.get("name") or "")[:150],
                    "payment_type": item["payment_type"],
                    "day_of_month": int(item["day_of_month"]),
                    "billing_month_mode": item.get(
                        "billing_month_mode", AutoRequestTemplate.BILLING_MONTH_CURRENT
                    ),
                    "title_template": str(item.get("title_template") or "")[:200],
                    "description_template": str(item.get("description_template") or ""),
                    "company_payer": "",
                    "amount": item.get("amount"),
                    "currency": item.get("currency", Request.CURRENCY_UZS),
                    "urgency": item.get("urgency", Request.URGENCY_NORMAL),
                    "payment_purpose": str(item.get("payment_purpose") or "")[:200],
                    "vendor_ref_id": vendor_ref_id if vendor_ref_id else None,
                    "requester_id": requester_id,
                    "updated_by": request.user,
                }
                if row_id:
                    row = existing.get(int(row_id))
                    if not row:
                        raise ValidationError({"id": f"Template {row_id} not found."})
                    for key, value in defaults.items():
                        setattr(row, key, value)
                    row.save()
                    seen_ids.add(row.id)
                else:
                    row = AutoRequestTemplate.objects.create(tenant=tenant, **defaults)
                    seen_ids.add(row.id)

            for row in existing.values():
                if row.id not in seen_ids:
                    row.delete()

        return Response(build_auto_request_config_response(tenant=tenant))

