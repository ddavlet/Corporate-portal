import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.investments.approval_services import (
    InvestmentApprovalDecisionAlreadyMade,
    confirm_invest_return_approval_by_id,
    create_approvals_for_invest_return,
    route_invest_return_approvals,
)
from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentReturnApproval,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
)
from apps.modules.investments.serializers import (
    InvestCompanySerializer,
    InvestmentApprovalConfigSerializer,
    InvestmentApprovalDecisionSerializer,
    InvestmentApprovalWebhookSerializer,
    InvestPayoutScheduleSerializer,
    InvestPayoutScheduleShareLinkSerializer,
    InvestReturnSerializer,
    PublicInvestPayoutScheduleShareViewSerializer,
    ProjectInvestmentSerializer,
)
from apps.tenants.permissions import HasEffectiveModuleAccess


class _InvestmentsTenantViewSet(viewsets.ModelViewSet):
    module_key = "investments"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return self.queryset.none()
        return self.queryset.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)


class InvestReturnViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestReturnSerializer
    queryset = InvestReturn.objects.all()

    def perform_create(self, serializer):
        obj = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        create_approvals_for_invest_return(invest_return=obj)
        route_invest_return_approvals(invest_return=obj)


class InvestPayoutScheduleViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestPayoutScheduleSerializer
    queryset = InvestPayoutSchedule.objects.all()


class ProjectInvestmentViewSet(_InvestmentsTenantViewSet):
    serializer_class = ProjectInvestmentSerializer
    queryset = ProjectInvestment.objects.all()


class InvestCompanyViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestCompanySerializer
    queryset = InvestCompany.objects.all()


class InvestPayoutScheduleShareLinkViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestPayoutScheduleShareLinkSerializer
    queryset = InvestPayoutScheduleShareLink.objects.all()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(is_active=True).select_related("company")

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])


class PublicInvestPayoutScheduleByTokenView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token: str):
        link = (
            InvestPayoutScheduleShareLink.objects.filter(token=token, is_active=True)
            .select_related("company", "tenant")
            .first()
        )
        if not link:
            return Response({"detail": "Link not found."}, status=status.HTTP_404_NOT_FOUND)

        qs = InvestPayoutSchedule.objects.filter(tenant=link.tenant).select_related("company")
        if link.company_id:
            qs = qs.filter(company_id=link.company_id)
        if link.paid_filter == InvestPayoutScheduleShareLink.PaidFilter.PAID:
            qs = qs.filter(is_paid=True)
        elif link.paid_filter == InvestPayoutScheduleShareLink.PaidFilter.UNPAID:
            qs = qs.filter(is_paid=False)

        rows = [
            {
                "id": row.id,
                "payout_date": row.payout_date,
                "amount": row.amount,
                "is_paid": row.is_paid,
                "payment_amount": row.payment_amount,
                "comment": row.comment,
                "company": row.company_id,
                "company_name": row.company.name if row.company else "",
                "currency": row.currency,
            }
            for row in qs.order_by("payout_date", "id")
        ]
        return Response(
            {
                "filters": {
                    "company": link.company_id,
                    "company_name": link.company.name if link.company else "",
                    "tenant_name": link.tenant.name,
                    "paid_filter": link.paid_filter,
                },
                "rows": PublicInvestPayoutScheduleShareViewSerializer(rows, many=True).data,
            }
        )


class InvestmentApprovalConfigView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    def _get_or_create(self, tenant):
        config, _ = InvestmentApprovalConfig.objects.get_or_create(tenant=tenant)
        return config

    def _response_payload(self, tenant):
        config = self._get_or_create(tenant)
        steps = list(config.steps.order_by("step", "id").prefetch_related("approver_users"))
        User = get_user_model()
        approver_candidates = list(
            User.objects.filter(tenant_memberships__tenant=tenant, is_active=True)
            .distinct()
            .order_by("username")
            .values("id", "username")
        )
        return {
            "is_enabled": config.is_enabled,
            "steps": [
                {
                    "step": row.step,
                    "is_enabled": row.is_enabled,
                    "approver_user_ids": list(row.approver_users.values_list("id", flat=True)),
                }
                for row in steps
            ],
            "approver_candidates": approver_candidates,
        }

    def get(self, request):
        self.check_permissions(request)
        return Response(self._response_payload(request.tenant))

    def put(self, request):
        self.check_permissions(request)
        serializer = InvestmentApprovalConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        with transaction.atomic():
            config = self._get_or_create(request.tenant)
            config.is_enabled = payload["is_enabled"]
            config.save(update_fields=["is_enabled", "updated_at"])
            config.steps.all().delete()
            for row in payload["steps"]:
                step = InvestmentApprovalConfigStep.objects.create(
                    config=config,
                    step=row["step"],
                    is_enabled=row["is_enabled"],
                )
                step.approver_users.set(row["approver_user_ids"])
        return Response(self._response_payload(request.tenant))


class InvestmentApprovalDecisionView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    def post(self, request, approval_id: int):
        self.check_permissions(request)
        serializer = InvestmentApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        try:
            result = confirm_invest_return_approval_by_id(
                tenant=request.tenant,
                approval_id=approval_id,
                approver_tg_id=payload.get("approver_tg_id"),
                approver_tg_from_id=payload.get("approver_tg_from_id"),
                decision=payload["decision"],
                comment=payload.get("comment", ""),
            )
        except InvestmentApprovalDecisionAlreadyMade:
            return Response({"detail": "Decision already made."}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(
            {
                "approval_id": result.approval.id,
                "decision": result.approval.decision,
                "invest_return": {"id": result.invest_return.id, "confirmed": result.invest_return.confirmed},
            }
        )


class InvestmentApprovalWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def _check_token(self, request):
        tenant = getattr(request, "tenant", None)
        config = self._resolve_config_token(tenant)
        if not config:
            return
        got = (request.META.get("HTTP_X_N8N_INTEGRATION_TOKEN", "") or "").strip()
        if got != config:
            raise ValidationError({"detail": "Invalid webhook token."})

    def _resolve_config_token(self, tenant) -> str:
        from apps.modules.requests.integration_settings import get_requests_telegram_integration_settings

        token = get_requests_telegram_integration_settings(tenant=tenant).n8n_integration_token
        if token:
            return token
        return (getattr(settings, "N8N_INTEGRATION_TOKEN", "") or "").strip()

    def _extract_update(self, payload: dict) -> dict:
        if isinstance(payload.get("update"), dict):
            return payload["update"]
        return payload

    def _parse_callback_data(self, callback_data: str | None) -> tuple[int | None, str]:
        if not callback_data:
            raise ValidationError({"detail": "callback_query.data is required."})
        raw = callback_data.strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                decoded_raw = json.loads(raw)
                if isinstance(decoded_raw, str):
                    raw = decoded_raw.strip()
            except json.JSONDecodeError:
                pass
        if raw.startswith("inv_") and ":" in raw and raw.count(":") == 1:
            left, right = raw[4:].split(":", 1)
            try:
                approval_id = int(left)
            except (TypeError, ValueError):
                approval_id = None
            code = right.strip().lower()
            if code == "a":
                return approval_id, InvestmentReturnApproval.DECISION_APPROVED
            if code == "r":
                return approval_id, InvestmentReturnApproval.DECISION_REJECTED
        raise ValidationError({"detail": "Unsupported decision value in callback data."})

    def post(self, request):
        self._check_token(request)
        serializer = InvestmentApprovalWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        update = self._extract_update(payload)
        callback_query = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else None
        if callback_query is None:
            return Response({"detail": "Only callback_query updates are supported."}, status=status.HTTP_202_ACCEPTED)

        parsed_approval_id, decision = self._parse_callback_data(callback_query.get("data"))
        if parsed_approval_id is None:
            raise ValidationError({"approval_id": "approval_id is required and must be integer."})

        from_obj = callback_query.get("from") if isinstance(callback_query.get("from"), dict) else {}
        message_obj = callback_query.get("message") if isinstance(callback_query.get("message"), dict) else {}
        chat_obj = message_obj.get("chat") if isinstance(message_obj.get("chat"), dict) else {}
        try:
            from_id = int(from_obj.get("id"))
            chat_id = int(chat_obj.get("id"))
            message_id = int(message_obj.get("message_id"))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": "Invalid callback identifiers."}) from exc

        approval = InvestmentReturnApproval.objects.select_related("tenant").filter(id=parsed_approval_id).first()
        if not approval:
            raise ValidationError({"approval_id": "Approval not found."})
        if approval.message_id is not None and approval.message_id != message_id:
            raise ValidationError({"message_id": "Callback message_id does not match stored message_id."})
        if approval.approver_tg_id is not None and approval.approver_tg_id != chat_id:
            raise ValidationError({"chat_id": "Chat is not allowed for this approval."})
        if approval.approver_tg_from_id is not None and approval.approver_tg_from_id != from_id:
            raise ValidationError({"from_id": "User is not allowed for this approval."})

        if approval.message_id is None:
            approval.message_id = message_id
            approval.message_sent = True
            if approval.message_sent_at is None:
                from django.utils import timezone

                approval.message_sent_at = timezone.now()
            approval.save(update_fields=["message_id", "message_sent", "message_sent_at"])

        try:
            confirm_invest_return_approval_by_id(
                tenant=approval.tenant,
                approval_id=approval.id,
                approver_tg_id=chat_id,
                approver_tg_from_id=from_id,
                decision=decision,
            )
        except InvestmentApprovalDecisionAlreadyMade:
            return Response({"detail": "Decision already made."}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response({"detail": "Callback processed."}, status=status.HTTP_200_OK)
