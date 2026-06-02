import json
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
    deactivate_investment_return_approval_buttons,
    route_invest_return_approvals,
)
from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentFormConfig,
    InvestmentProjectApprovalConfig,
    InvestmentProjectApprovalConfigStep,
    InvestmentProjectApprovalConfigStepApprover,
    InvestmentReturnApproval,
    InvestNotificationConfig,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.investments.project_investment_approval_services import (
    InvestmentProjectApprovalDecisionAlreadyMade,
    confirm_project_investment_approval_by_id,
    create_approvals_for_project_investment,
    deactivate_project_investment_approval_buttons,
    route_project_investment_approvals,
)
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.modules.investments.serializers import (
    InvestCompanySerializer,
    InvestmentApprovalConfigReadSerializer,
    InvestmentApprovalConfigSerializer,
    InvestmentApprovalConfigStepApproverReadSerializer,
    InvestmentApprovalConfigStepReadSerializer,
    InvestmentApprovalDecisionSerializer,
    InvestmentApprovalWebhookSerializer,
    InvestmentFormConfigReadSerializer,
    InvestmentFormConfigSerializer,
    InvestmentProjectApprovalConfigReadSerializer,
    InvestmentProjectApprovalConfigSerializer,
    InvestmentProjectApprovalConfigStepApproverReadSerializer,
    InvestmentProjectApprovalConfigStepReadSerializer,
    InvestmentReturnApprovalReadSerializer,
    InvestNotificationConfigSerializer,
    InvestPayoutScheduleSerializer,
    InvestPayoutScheduleShareLinkSerializer,
    InvestReturnSerializer,
    PublicInvestPayoutScheduleShareViewSerializer,
    ProjectInvestmentApprovalReadSerializer,
    ProjectInvestmentSerializer,
)
from apps.common.pagination import PortalCursorPagination
from apps.common.query_params import parse_bool_query, parse_date_query
from apps.common.viewsets import NoPortalPaginationMixin, PortalListViewSetMixin
from apps.modules.telegram_approvals.services import ensure_callback_identity
from apps.tenants.models import TenantMembership
from apps.tenants.permissions import HasEffectiveModuleAccess


class _InvestmentsTenantViewSet(PortalListViewSetMixin, viewsets.ModelViewSet):
    module_key = "investments"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    pagination_class = PortalCursorPagination
    ordering_fields = ["id", "created_at"]
    ordering = ["-id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return self.queryset.none()
        return self.queryset.filter(tenant=tenant).order_by("-id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)


class _ReadOnlyInvestmentsTenantViewSet(NoPortalPaginationMixin, viewsets.ReadOnlyModelViewSet):
    """Список строк таблицы модуля «Инвестиции» для админ-просмотра (без изменений через API)."""

    module_key = "investments"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return self.queryset.none()
        return self.queryset.filter(tenant=tenant)


class InvestmentFormConfigReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentFormConfigReadSerializer
    queryset = InvestmentFormConfig.objects.all()


class InvestmentApprovalConfigReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentApprovalConfigReadSerializer
    queryset = InvestmentApprovalConfig.objects.all()


class InvestmentApprovalConfigStepReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentApprovalConfigStepReadSerializer
    queryset = InvestmentApprovalConfigStep.objects.select_related("config")

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return InvestmentApprovalConfigStep.objects.none()
        return InvestmentApprovalConfigStep.objects.filter(config__tenant=tenant).select_related("config")


class InvestmentApprovalConfigStepApproverReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentApprovalConfigStepApproverReadSerializer
    queryset = InvestmentApprovalConfigStepApprover.objects.select_related("step__config")

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return InvestmentApprovalConfigStepApprover.objects.none()
        return InvestmentApprovalConfigStepApprover.objects.filter(step__config__tenant=tenant).select_related(
            "step", "step__config", "approver_user"
        )


class InvestmentReturnApprovalReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentReturnApprovalReadSerializer
    queryset = InvestmentReturnApproval.objects.select_related("invest_return", "approver_user")


class InvestmentProjectApprovalConfigReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentProjectApprovalConfigReadSerializer
    queryset = InvestmentProjectApprovalConfig.objects.all()


class InvestmentProjectApprovalConfigStepReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentProjectApprovalConfigStepReadSerializer
    queryset = InvestmentProjectApprovalConfigStep.objects.select_related("config")

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return InvestmentProjectApprovalConfigStep.objects.none()
        return InvestmentProjectApprovalConfigStep.objects.filter(config__tenant=tenant).select_related("config")


class InvestmentProjectApprovalConfigStepApproverReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = InvestmentProjectApprovalConfigStepApproverReadSerializer
    queryset = InvestmentProjectApprovalConfigStepApprover.objects.select_related("step__config")

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return InvestmentProjectApprovalConfigStepApprover.objects.none()
        return InvestmentProjectApprovalConfigStepApprover.objects.filter(step__config__tenant=tenant).select_related(
            "step", "step__config", "approver_user"
        )


class ProjectInvestmentApprovalReadViewSet(_ReadOnlyInvestmentsTenantViewSet):
    serializer_class = ProjectInvestmentApprovalReadSerializer
    queryset = ProjectInvestmentApproval.objects.select_related("project_investment", "approver_user")


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
    ordering_fields = ["payout_date", "amount", "id", "is_paid"]
    ordering = ["-payout_date", "-id"]

    def get_queryset(self):
        qs = super().get_queryset()
        company_id = (self.request.query_params.get("company") or "").strip()
        if company_id.isdigit():
            qs = qs.filter(company_id=int(company_id))
        is_paid = parse_bool_query(self.request, "is_paid")
        if is_paid is True:
            qs = qs.filter(is_paid=True)
        elif is_paid is False:
            qs = qs.filter(is_paid=False)
        payout_from = parse_date_query(self.request, "payout_from")
        payout_to = parse_date_query(self.request, "payout_to")
        if payout_from:
            qs = qs.filter(payout_date__gte=payout_from)
        if payout_to:
            qs = qs.filter(payout_date__lte=payout_to)
        return qs.order_by("-payout_date", "-id")


class ProjectInvestmentViewSet(_InvestmentsTenantViewSet):
    serializer_class = ProjectInvestmentSerializer
    queryset = ProjectInvestment.objects.all()

    def perform_create(self, serializer):
        obj = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        create_approvals_for_project_investment(project_investment=obj)
        route_project_investment_approvals(project_investment=obj)


class InvestCompanyViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestCompanySerializer
    queryset = InvestCompany.objects.all()
    ordering_fields = ["name", "id", "created_at"]
    ordering = ["name", "id"]

    def get_queryset(self):
        qs = super().get_queryset()
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            from django.db.models import Q

            qs = qs.filter(Q(name__icontains=search))
        return qs.order_by("name", "id")

    def perform_create(self, serializer):
        cfg = InvestmentFormConfig.objects.filter(tenant=self.request.tenant).first()
        if cfg and not cfg.uses_companies:
            raise ValidationError({"detail": "Создание компаний отключено в настройках формы инвестиций."})
        super().perform_create(serializer)


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


class InvestmentFormConfigView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    @staticmethod
    def _all_return_type_values() -> list[str]:
        return [c[0] for c in InvestReturn.ReturnType.choices]

    def _payload(self, tenant):
        cfg = InvestmentFormConfig.objects.filter(tenant=tenant).first()
        choices_payload = [{"value": c[0], "label": str(c[1])} for c in InvestReturn.ReturnType.choices]
        all_values = self._all_return_type_values()
        if not cfg:
            return {
                "uses_companies": True,
                "allowed_return_types": all_values,
                "return_type_choices": choices_payload,
            }
        allowed = list(cfg.allowed_return_types or [])
        if not allowed:
            allowed = all_values
        return {
            "uses_companies": cfg.uses_companies,
            "allowed_return_types": allowed,
            "return_type_choices": choices_payload,
        }

    def get(self, request):
        self.check_permissions(request)
        return Response(self._payload(request.tenant))

    def put(self, request):
        self.check_permissions(request)
        serializer = InvestmentFormConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        InvestmentFormConfig.objects.update_or_create(
            tenant=request.tenant,
            defaults={
                "uses_companies": payload["uses_companies"],
                "allowed_return_types": list(payload["allowed_return_types"]),
            },
        )
        return Response(self._payload(request.tenant))


class InvestNotificationConfigView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    def _payload(self, tenant):
        cfg = InvestNotificationConfig.objects.filter(tenant=tenant).select_related("responsible_user", "telegram_chat").first()
        User = get_user_model()
        member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
        candidates = list(
            User.objects.filter(id__in=member_ids, is_active=True)
            .order_by("username")
            .values("id", "username", "full_name")
        )
        approver_candidates = [
            {"id": u["id"], "label": (u["full_name"] or u["username"]).strip(), "username": u["username"]}
            for u in candidates
        ]
        meta = InvestNotificationConfig._meta
        if not cfg:
            return {
                "is_active": False,
                "days_before": meta.get_field("days_before").default,
                "overdue_notify_every_days": meta.get_field("overdue_notify_every_days").default,
                "notify_hour": meta.get_field("notify_hour").default,
                "responsible_user_id": None,
                "responsible_user_name": "",
                "telegram_chat_id": None,
                "approver_candidates": approver_candidates,
            }
        user = cfg.responsible_user
        return {
            "is_active": cfg.is_active,
            "days_before": cfg.days_before,
            "overdue_notify_every_days": cfg.overdue_notify_every_days,
            "notify_hour": cfg.notify_hour,
            "responsible_user_id": user.pk,
            "responsible_user_name": (getattr(user, "full_name", "") or user.username or "").strip(),
            "telegram_chat_id": cfg.telegram_chat_id,
            "approver_candidates": approver_candidates,
        }

    def get(self, request):
        self.check_permissions(request)
        return Response(self._payload(request.tenant))

    def put(self, request):
        self.check_permissions(request)
        serializer = InvestNotificationConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        User = get_user_model()
        # Scope to active members of THIS tenant: the responsible user receives Telegram
        # notifications containing payout amounts, so a foreign user must never be assignable.
        is_member = TenantMembership.objects.filter(
            tenant=request.tenant,
            user_id=payload["responsible_user_id"],
            is_active=True,
        ).exists()
        if not is_member:
            raise ValidationError({"responsible_user_id": "User is not an active member of this tenant."})
        try:
            user = User.objects.get(pk=payload["responsible_user_id"])
        except User.DoesNotExist:
            raise ValidationError({"responsible_user_id": "User not found."})
        InvestNotificationConfig.objects.update_or_create(
            tenant=request.tenant,
            defaults={
                "responsible_user": user,
                "days_before": payload["days_before"],
                "overdue_notify_every_days": payload["overdue_notify_every_days"],
                "notify_hour": payload["notify_hour"],
                "is_active": payload["is_active"],
                "telegram_chat_id": payload.get("telegram_chat_id") or None,
            },
        )
        return Response(self._payload(request.tenant))


class InvestPayoutScheduleCreateReturnView(APIView):
    """Web one-click: create-or-return the InvestReturn for a payout schedule.

    Uses the same atomic helper as the Telegram callback so concurrent presses (web tab
    or Telegram tap) all converge on the single ``created_return`` FK — no duplicates.
    """

    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    def post(self, request, schedule_id: int):
        self.check_permissions(request)
        from apps.modules.investments.notification_services import create_or_get_return_for_schedule

        schedule = (
            InvestPayoutSchedule.objects
            .select_related("tenant", "company")
            .filter(pk=schedule_id, tenant=request.tenant)
            .first()
        )
        if schedule is None:
            return Response({"detail": "Schedule not found."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            invest_return, was_created, note = create_or_get_return_for_schedule(
                schedule=schedule, created_by=request.user,
            )
        return Response(
            {"detail": note, "return_id": invest_return.pk if invest_return else None},
            status=status.HTTP_201_CREATED if was_created else status.HTTP_200_OK,
        )


class InvestPayoutScheduleMarkPaidView(APIView):
    """Mark a payout as paid without going through the request flow (paid out-of-band)."""

    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    def post(self, request, schedule_id: int):
        self.check_permissions(request)
        with transaction.atomic():
            schedule = (
                InvestPayoutSchedule.objects
                .select_for_update(of=("self",))
                .filter(pk=schedule_id, tenant=request.tenant)
                .first()
            )
            if schedule is None:
                return Response({"detail": "Schedule not found."}, status=status.HTTP_404_NOT_FOUND)
            if schedule.is_paid:
                return Response({"detail": "Already paid.", "is_paid": True}, status=status.HTTP_200_OK)
            schedule.is_paid = True
            # Quick action assumes the scheduled amount was paid in full. Users who paid a
            # different amount can correct via the schedule edit form.
            if not schedule.payment_amount:
                schedule.payment_amount = schedule.amount
            schedule.save(update_fields=["is_paid", "payment_amount", "last_edit_at"])
        return Response({"detail": "Marked as paid.", "is_paid": True}, status=status.HTTP_200_OK)


class InvestmentApprovalConfigView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    @staticmethod
    def _parse_return_type_param(raw) -> str | None:
        if raw in (None, "", "null"):
            return None
        valid = {c[0] for c in InvestReturn.ReturnType.choices}
        if raw not in valid:
            raise ValidationError({"return_type": "Недопустимый тип выплаты."})
        return raw

    @staticmethod
    def _parse_recipient_param(raw) -> str | None:
        if raw in (None, "", "null"):
            return None
        valid = {c[0] for c in InvestReturn.Recipient.choices}
        if raw not in valid:
            raise ValidationError({"recipient": "Недопустимый получатель."})
        return raw

    def _get_or_create(self, tenant, return_type: str | None, recipient: str | None):
        config, _ = InvestmentApprovalConfig.objects.get_or_create(
            tenant=tenant,
            return_type=return_type,
            recipient=recipient,
            defaults={"is_enabled": False},
        )
        return config

    def _response_payload(self, tenant, return_type: str | None, recipient: str | None):
        config = self._get_or_create(tenant, return_type, recipient)
        steps = list(config.steps.order_by("step", "id").prefetch_related("approver_users"))
        User = get_user_model()
        member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list(
            "user_id", flat=True
        )
        approver_candidates = list(
            User.objects.filter(id__in=member_ids, is_active=True)
            .distinct()
            .order_by("username")
            .values("id", "username")
        )
        return {
            "return_type": config.return_type,
            "recipient": config.recipient,
            "return_type_choices": [{"value": c[0], "label": c[1]} for c in InvestReturn.ReturnType.choices],
            "recipient_choices": [{"value": c[0], "label": c[1]} for c in InvestReturn.Recipient.choices],
            "is_enabled": config.is_enabled,
            "steps": [
                {
                    "step": row.step,
                    "step_type": row.step_type,
                    "is_enabled": row.is_enabled,
                    "telegram_chat_id": row.telegram_chat_id,
                    "approver_user_ids": list(row.approver_users.values_list("id", flat=True)),
                }
                for row in steps
            ],
            "approver_candidates": approver_candidates,
        }

    def get(self, request):
        self.check_permissions(request)
        rt = self._parse_return_type_param(request.query_params.get("return_type"))
        rec = self._parse_recipient_param(request.query_params.get("recipient"))
        return Response(self._response_payload(request.tenant, rt, rec))

    def put(self, request):
        self.check_permissions(request)
        serializer = InvestmentApprovalConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        cfg_return_type = payload.get("return_type")
        cfg_recipient = payload.get("recipient")

        with transaction.atomic():
            config = self._get_or_create(request.tenant, cfg_return_type, cfg_recipient)
            config.is_enabled = payload["is_enabled"]
            config.save(update_fields=["is_enabled", "updated_at"])
            config.steps.all().delete()
            for row in payload["steps"]:
                step = InvestmentApprovalConfigStep.objects.create(
                    config=config,
                    step=row["step"],
                    step_type=row.get("step_type", InvestmentApprovalConfigStep.STEP_TYPE_SERIAL),
                    is_enabled=row["is_enabled"],
                    telegram_chat_id=row.get("telegram_chat_id"),
                )
                step.approver_users.set(row.get("approver_user_ids") or [])
        return Response(
            self._response_payload(request.tenant, config.return_type, config.recipient),
        )


class InvestmentProjectApprovalConfigView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    def _get_or_create(self, tenant):
        config, _ = InvestmentProjectApprovalConfig.objects.get_or_create(
            tenant=tenant,
            defaults={"is_enabled": False},
        )
        return config

    def _response_payload(self, tenant):
        config = self._get_or_create(tenant)
        steps = list(config.steps.order_by("step", "id").prefetch_related("approver_users"))
        User = get_user_model()
        member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list(
            "user_id", flat=True
        )
        approver_candidates = list(
            User.objects.filter(id__in=member_ids, is_active=True)
            .distinct()
            .order_by("username")
            .values("id", "username")
        )
        return {
            "is_enabled": config.is_enabled,
            "steps": [
                {
                    "step": row.step,
                    "step_type": row.step_type,
                    "is_enabled": row.is_enabled,
                    "telegram_chat_id": row.telegram_chat_id,
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
        serializer = InvestmentProjectApprovalConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        with transaction.atomic():
            config = self._get_or_create(request.tenant)
            config.is_enabled = payload["is_enabled"]
            config.save(update_fields=["is_enabled", "updated_at"])
            config.steps.all().delete()
            for row in payload["steps"]:
                step = InvestmentProjectApprovalConfigStep.objects.create(
                    config=config,
                    step=row["step"],
                    step_type=row.get("step_type", InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL),
                    is_enabled=row["is_enabled"],
                    telegram_chat_id=row.get("telegram_chat_id"),
                )
                step.approver_users.set(row.get("approver_user_ids") or [])
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
                approver_recipient_id=payload.get("approver_recipient_id"),
                approver_external_user_id=payload.get("approver_external_user_id"),
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


class InvestmentProjectApprovalDecisionView(APIView):
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    module_key = "investments"

    def post(self, request, approval_id: int):
        self.check_permissions(request)
        serializer = InvestmentApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        try:
            result = confirm_project_investment_approval_by_id(
                tenant=request.tenant,
                approval_id=approval_id,
                approver_recipient_id=payload.get("approver_recipient_id"),
                approver_external_user_id=payload.get("approver_external_user_id"),
                decision=payload["decision"],
                comment=payload.get("comment", ""),
            )
        except InvestmentProjectApprovalDecisionAlreadyMade:
            return Response({"detail": "Decision already made."}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(
            {
                "approval_id": result.approval.id,
                "decision": result.approval.decision,
                "project_investment": {
                    "id": result.project_investment.id,
                    "confirmed": result.project_investment.confirmed,
                },
            }
        )


class InvestmentApprovalWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def _parse_callback_data(self, callback_data: str | None) -> tuple[str, int | None, str]:
        """
        Returns (kind, approval_id, decision) where kind is 'return' or 'project'.
        """
        if not callback_data:
            raise ValidationError({"detail": "payload (callback data) is required."})
        raw = callback_data.strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                decoded_raw = json.loads(raw)
                if isinstance(decoded_raw, str):
                    raw = decoded_raw.strip()
            except json.JSONDecodeError:
                pass
        if raw.startswith("invp_") and ":" in raw and raw.count(":") == 1:
            left, right = raw[5:].split(":", 1)
            try:
                approval_id = int(left)
            except (TypeError, ValueError):
                approval_id = None
            code = right.strip().lower()
            if code == "a":
                return "project", approval_id, ProjectInvestmentApproval.DECISION_APPROVED
            if code == "r":
                return "project", approval_id, ProjectInvestmentApproval.DECISION_REJECTED
        if raw.startswith("inv_") and ":" in raw and raw.count(":") == 1:
            left, right = raw[4:].split(":", 1)
            try:
                approval_id = int(left)
            except (TypeError, ValueError):
                approval_id = None
            code = right.strip().lower()
            if code == "a":
                return "return", approval_id, InvestmentReturnApproval.DECISION_APPROVED
            if code == "r":
                return "return", approval_id, InvestmentReturnApproval.DECISION_REJECTED
        raise ValidationError({"detail": "Unsupported decision value in callback payload."})

    def post(self, request):
        serializer = InvestmentApprovalWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event_data = serializer.validated_data
        if event_data.get("event") != "interaction":
            return Response({"detail": "Only interaction events are supported."}, status=status.HTTP_202_ACCEPTED)

        kind, parsed_approval_id, decision = self._parse_callback_data(event_data.get("payload"))
        if parsed_approval_id is None:
            raise ValidationError({"approval_id": "approval_id is required and must be integer."})

        try:
            from_id = int(event_data["user_id"])
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": "Invalid callback identifiers."}) from exc
        chat_id = str(event_data["recipient_id"]).strip() if event_data.get("recipient_id") is not None else None
        message_id = event_data.get("message_id")

        if kind == "project":
            approval = ProjectInvestmentApproval.objects.select_related("tenant").filter(id=parsed_approval_id).first()
            if not approval:
                raise ValidationError({"approval_id": "Approval not found."})
            if approval.step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION:
                raise ValidationError({"detail": "Этап notification не принимает ответы по кнопкам."})
            ensure_callback_identity(
                callback_message_id=message_id,
                stored_message_id=approval.gateway_message_id,
                callback_recipient_id=chat_id,
                stored_recipient_id=approval.approver_recipient_id,
                callback_external_user_id=from_id,
                stored_external_user_id=approval.approver_external_user_id,
            )

            if message_id is not None and approval.telegram_message_id is None:
                tg_message = TelegramMessage.objects.create(
                    tenant=approval.tenant,
                    recipient_id=str(approval.approver_recipient_id or chat_id or ""),
                    external_user_id=approval.approver_external_user_id,
                    message_id=message_id,
                    sent_at=timezone.now(),
                )
                approval.telegram_message = tg_message
                approval.save(update_fields=["telegram_message"])

            try:
                confirm_project_investment_approval_by_id(
                    tenant=approval.tenant,
                    approval_id=approval.id,
                    approver_recipient_id=chat_id,
                    approver_external_user_id=from_id,
                    decision=decision,
                )
            except InvestmentProjectApprovalDecisionAlreadyMade:
                approval.refresh_from_db()
                deactivate_project_investment_approval_buttons(approval=approval)
                return Response({"detail": "Decision already made."}, status=status.HTTP_409_CONFLICT)
            except ValueError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            return Response({"detail": "Callback processed."}, status=status.HTTP_200_OK)

        approval = InvestmentReturnApproval.objects.select_related("tenant").filter(id=parsed_approval_id).first()
        if not approval:
            raise ValidationError({"approval_id": "Approval not found."})
        if approval.step_type == InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION:
            raise ValidationError({"detail": "Этап notification не принимает ответы по кнопкам."})
        ensure_callback_identity(
            callback_message_id=message_id,
            stored_message_id=approval.gateway_message_id,
            callback_recipient_id=chat_id,
            stored_recipient_id=approval.approver_recipient_id,
            callback_external_user_id=from_id,
            stored_external_user_id=approval.approver_external_user_id,
        )

        if message_id is not None and approval.telegram_message_id is None:
            tg_message = TelegramMessage.objects.create(
                tenant=approval.tenant,
                recipient_id=str(approval.approver_recipient_id or chat_id or ""),
                external_user_id=approval.approver_external_user_id,
                message_id=message_id,
                sent_at=timezone.now(),
            )
            approval.telegram_message = tg_message
            approval.save(update_fields=["telegram_message"])

        try:
            confirm_invest_return_approval_by_id(
                tenant=approval.tenant,
                approval_id=approval.id,
                approver_recipient_id=chat_id,
                approver_external_user_id=from_id,
                decision=decision,
            )
        except InvestmentApprovalDecisionAlreadyMade:
            approval.refresh_from_db()
            deactivate_investment_return_approval_buttons(approval=approval)
            return Response({"detail": "Decision already made."}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response({"detail": "Callback processed."}, status=status.HTTP_200_OK)
