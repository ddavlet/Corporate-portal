from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.tenants.models import TenantIntegrationConfig, TenantModuleConfig
from apps.tenants.permissions import IsTenantAdmin, role_allows_module
from apps.tenants.serializers import (
    TenantIntegrationConfigSerializer,
    TenantModuleConfigUpdateSerializer,
)
from apps.tenants.integration_settings import (
    get_n8n_integration_settings,
    get_portal_feedback_settings,
    get_requests_gateway_settings,
    get_telegram_approvals_settings,
)

from apps.modules.registry import list_modules

User = get_user_model()


class ModuleCatalogView(APIView):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant"}, status=status.HTTP_404_NOT_FOUND)

        out = []
        for m in list_modules():
            module_key = m["module_key"]
            tenant_enabled = TenantModuleConfig.objects.filter(
                tenant=tenant, module_key=module_key, is_enabled=True
            ).exists()
            user_allowed = role_allows_module(user=request.user, tenant=tenant, module_key=module_key)
            effective_enabled = tenant_enabled and user_allowed

            out.append(
                {
                    "module_key": module_key,
                    "display_name": m["display_name"],
                    "tenant_enabled": tenant_enabled,
                    "user_allowed": user_allowed,
                    "effective_enabled": effective_enabled,
                }
            )

        return Response({"modules": out})


class TenantModuleConfigView(APIView):
    permission_classes = [IsTenantAdmin]

    def get(self, request):
        tenant = request.tenant
        items = []
        for m in list_modules():
            is_enabled = TenantModuleConfig.objects.filter(
                tenant=tenant, module_key=m["module_key"], is_enabled=True
            ).exists()
            items.append({"module_key": m["module_key"], "is_enabled": is_enabled})
        return Response({"items": items})

    def put(self, request):
        tenant = request.tenant
        serializer = TenantModuleConfigUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        module_items = serializer.validated_data["items"]
        module_keys = [x["module_key"] for x in module_items]

        # Upsert rows.
        for row in module_items:
            cfg, _ = TenantModuleConfig.objects.update_or_create(
                tenant=tenant, module_key=row["module_key"], defaults={"is_enabled": row["is_enabled"]}
            )

        # Optional: disable all modules not present.
        # Keeping it explicit: only apply provided items for now.
        return Response({"items": list(serializer.validated_data["items"])})


class TenantIntegrationConfigView(APIView):
    permission_classes = [IsTenantAdmin]

    @staticmethod
    def _masked(value: str) -> str:
        return "********" if value else ""

    def get(self, request):
        tenant = request.tenant
        tg = get_telegram_approvals_settings(tenant=tenant)
        n8n = get_n8n_integration_settings(tenant=tenant)
        req = get_requests_gateway_settings(tenant=tenant)
        pf = get_portal_feedback_settings(tenant=tenant)
        return Response(
            {
                "telegram_bot_token": self._masked(tenant.get_telegram_bot_token()),
                "telegram_approvals_bridge_dispatch_url": tg.dispatch_url,
                "telegram_approvals_send_action": tg.send_action,
                "telegram_approvals_edit_action": tg.edit_action,
                "telegram_approvals_draft_notification_action": tg.draft_notification_action,
                "telegram_approvals_message_template": tg.message_template,
                "telegram_approvals_header_new_template": tg.header_new_template,
                "telegram_approvals_header_step_approved_template": tg.header_step_approved_template,
                "telegram_approvals_header_fully_approved_template": tg.header_fully_approved_template,
                "telegram_approvals_header_closed_template": tg.header_closed_template,
                "telegram_approvals_header_rejected_template": tg.header_rejected_template,
                "telegram_approvals_subheader_payment_responsible_template": tg.subheader_payment_responsible_template,
                "telegram_approvals_subheader_rejected_by_template": tg.subheader_rejected_by_template,
                "telegram_approvals_bridge_token": self._masked(tg.bridge_token),
                "n8n_integration_token": self._masked(n8n.integration_token),
                "requests_file_gateway_token": self._masked(req.bearer_token),
                "portal_feedback_telegram_chat_id": pf.telegram_chat_id,
                "portal_feedback_telegram_action": pf.telegram_action,
            }
        )

    def put(self, request):
        tenant = request.tenant
        payload = TenantIntegrationConfigSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=tenant)
        cfg.updated_by = request.user
        for field in (
            "telegram_approvals_bridge_dispatch_url",
            "telegram_approvals_send_action",
            "telegram_approvals_edit_action",
            "telegram_approvals_draft_notification_action",
            "telegram_approvals_message_template",
            "telegram_approvals_header_new_template",
            "telegram_approvals_header_step_approved_template",
            "telegram_approvals_header_fully_approved_template",
            "telegram_approvals_header_closed_template",
            "telegram_approvals_header_rejected_template",
            "telegram_approvals_subheader_payment_responsible_template",
            "telegram_approvals_subheader_rejected_by_template",
        ):
            if field in data:
                setattr(cfg, field, data[field])

        if "telegram_approvals_bridge_token" in data:
            cfg.set_telegram_approvals_bridge_token(data["telegram_approvals_bridge_token"])
        if "n8n_integration_token" in data:
            cfg.set_n8n_integration_token(data["n8n_integration_token"])
        if "requests_file_gateway_token" in data:
            cfg.set_requests_file_gateway_token(data["requests_file_gateway_token"])
        if "portal_feedback_telegram_chat_id" in data:
            cfg.portal_feedback_telegram_chat_id = data["portal_feedback_telegram_chat_id"]
        if "portal_feedback_telegram_action" in data:
            cfg.portal_feedback_telegram_action = data["portal_feedback_telegram_action"]
        if "telegram_bot_token" in data:
            tenant.set_telegram_bot_token(data["telegram_bot_token"])
        cfg.save()
        tenant.save(update_fields=["telegram_bot_token_enc"])
        return self.get(request)

