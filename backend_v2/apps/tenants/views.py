import logging
from django.contrib.auth import get_user_model
from collections import defaultdict

import requests
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from apps.tenants.models import (
    TenantIntegrationConfig,
    TenantMembership,
    TenantModuleConfig,
    TenantUserPreference,
    TenantUserRole,
)
from apps.tenants.permissions import IsTenantAdmin, role_allows_module
from apps.tenants.serializers import (
    TenantIntegrationConfigSerializer,
    TenantModuleConfigUpdateSerializer,
    TenantUserPreferenceSerializer,
)
from apps.tenants.integration_settings import get_portal_feedback_settings, get_requests_gateway_settings

from apps.modules.registry import list_modules

User = get_user_model()
logger = logging.getLogger(__name__)


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

        merged: defaultdict[str, bool] = defaultdict(bool)
        for row in TenantModuleConfig.objects.filter(tenant=tenant):
            merged[row.module_key] = row.is_enabled
        for row in module_items:
            merged[row["module_key"]] = row["is_enabled"]
        if merged["contracts"] and not merged["vendors"]:
            raise ValidationError(
                {"items": "Модуль «Договоры» требует включённый модуль «Поставщики»."}
            )

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

    @staticmethod
    def _gateway_base_url() -> str:
        return (getattr(settings, "MESSAGING_GATEWAY_ADMIN_URL", "") or "http://tg_gateway:8080").rstrip("/")

    @classmethod
    def _fetch_webhook_info(cls, bot_token: str) -> dict:
        if not bot_token:
            return {"connected": False, "url": "", "error": "Telegram bot token is not configured."}
        try:
            resp = requests.get(f"{cls._gateway_base_url()}/v1/messaging/webhook/info/{bot_token}", timeout=8)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400 or not data.get("ok"):
                detail = (data.get("telegram") or {}).get("description") if isinstance(data, dict) else None
                return {"connected": False, "url": "", "error": detail or f"Gateway HTTP {resp.status_code}"}
            return {
                "connected": bool(data.get("connected")),
                "url": str(data.get("url") or ""),
                "error": str(data.get("last_error_message") or "") or None,
            }
        except Exception as exc:
            return {"connected": False, "url": "", "error": str(exc)}

    def get(self, request):
        tenant = request.tenant
        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=tenant)
        req = get_requests_gateway_settings(tenant=tenant)
        pf = get_portal_feedback_settings(tenant=tenant)
        webhook = self._fetch_webhook_info(tenant.get_telegram_bot_token())
        return Response(
            {
                "telegram_bot_token": self._masked(tenant.get_telegram_bot_token()),
                "telegram_bot_username": tenant.telegram_bot_username or "",
                "requests_file_gateway_token": self._masked(req.bearer_token),
                "telegram_oidc_client_id": cfg.telegram_oidc_client_id,
                "telegram_oidc_client_secret": self._masked(cfg.get_telegram_oidc_client_secret()),
                "telegram_oidc_redirect_uri": cfg.telegram_oidc_redirect_uri,
                "messaging_gateway_feedback_recipient_id": pf.recipient_id,
                "messaging_gateway_feedback_action": pf.action,
                "messaging_gateway_webhook_connected": webhook["connected"],
                "messaging_gateway_webhook_url": webhook["url"],
                "messaging_gateway_webhook_error": webhook.get("error"),
            }
        )

    def put(self, request):
        tenant = request.tenant
        payload = TenantIntegrationConfigSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=tenant)
        cfg.updated_by = request.user
        if "requests_file_gateway_token" in data:
            cfg.set_requests_file_gateway_token(data["requests_file_gateway_token"])
        if "telegram_oidc_client_id" in data:
            cfg.telegram_oidc_client_id = data["telegram_oidc_client_id"].strip()
        if "telegram_oidc_client_secret" in data:
            cfg.set_telegram_oidc_client_secret(data["telegram_oidc_client_secret"])
        if "telegram_oidc_redirect_uri" in data:
            cfg.telegram_oidc_redirect_uri = data["telegram_oidc_redirect_uri"].strip()
        if "messaging_gateway_feedback_recipient_id" in data:
            cfg.messaging_gateway_feedback_recipient_id = data["messaging_gateway_feedback_recipient_id"]
        if "messaging_gateway_feedback_action" in data:
            cfg.messaging_gateway_feedback_action = data["messaging_gateway_feedback_action"]
        if "telegram_bot_token" in data:
            tenant.set_telegram_bot_token(data["telegram_bot_token"])
        if "telegram_bot_username" in data:
            tenant.telegram_bot_username = data["telegram_bot_username"].strip().lstrip("@")
        cfg.save()
        tenant.save(update_fields=["telegram_bot_token_enc", "telegram_bot_username"])
        return self.get(request)


class TenantMessagingWebhookView(APIView):
    permission_classes = [IsTenantAdmin]

    @staticmethod
    def _gateway_base_url() -> str:
        return (getattr(settings, "MESSAGING_GATEWAY_ADMIN_URL", "") or "http://tg_gateway:8080").rstrip("/")

    def post(self, request):
        action = str(request.data.get("action") or "").strip().lower()
        tenant = request.tenant
        bot_token = tenant.get_telegram_bot_token()
        if not bot_token:
            raise ValidationError({"detail": "Telegram bot token is not configured."})

        base = self._gateway_base_url()
        try:
            if action == "set":
                webhook_url = str(request.data.get("webhook_url") or "").strip()
                body = {"bot_token": bot_token}
                if webhook_url:
                    body["webhook_url"] = webhook_url
                resp = requests.post(f"{base}/v1/messaging/webhook/set", json=body, timeout=12)
            elif action == "delete":
                resp = requests.post(
                    f"{base}/v1/messaging/webhook/delete",
                    json={"bot_token": bot_token, "drop_pending_updates": True},
                    timeout=12,
                )
            elif action == "info":
                resp = requests.get(f"{base}/v1/messaging/webhook/info/{bot_token}", timeout=12)
            else:
                raise ValidationError({"action": "Expected one of: set, info, delete."})
        except requests.RequestException as exc:
            logger.exception("Messaging gateway webhook call failed action=%s tenant=%s", action, getattr(tenant, "pk", None))
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            return Response(
                {"detail": (payload.get("telegram") or {}).get("description") or f"Gateway HTTP {resp.status_code}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload)


class AccessMatrixView(APIView):
    """
    Admin-facing matrix of tenant users and their effective access.
    """

    permission_classes = [IsTenantAdmin]

    def get(self, request):
        tenant = request.tenant
        modules = list_modules()
        module_keys = [m["module_key"] for m in modules]

        memberships = (
            TenantMembership.objects.filter(tenant=tenant, is_active=True)
            .select_related("user")
            .order_by("user__username", "user_id")
        )
        roles_by_user: dict[int, list[str]] = {}
        for row in TenantUserRole.objects.filter(tenant=tenant).order_by("role"):
            roles_by_user.setdefault(row.user_id, []).append(row.role)

        users_payload = []
        for membership in memberships:
            user = membership.user
            roles = roles_by_user.get(user.id, [])
            module_access = {key: role_allows_module(user=user, tenant=tenant, module_key=key) for key in module_keys}
            users_payload.append(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "full_name": (getattr(user, "full_name", "") or "").strip(),
                    "roles": roles,
                    "module_access": module_access,
                    # Tenant settings remain admin-only even if user has broad module access.
                    "tenant_settings_access": TenantUserRole.ROLE_ADMIN in roles,
                }
            )

        return Response(
            {
                "modules": modules,
                "users": users_payload,
            }
        )


class SettingsAccessView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant"}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        roles = set(
            TenantUserRole.objects.filter(tenant=tenant, user=user).values_list("role", flat=True)
        )
        can_open_settings = (
            TenantUserRole.ROLE_ADMIN in roles
            or TenantUserRole.ROLE_DIRECTOR in roles
        )
        return Response(
            {
                "tenant_name": tenant.name,
                "can_open_settings": can_open_settings,
                "can_open_admin": TenantUserRole.ROLE_ADMIN in roles,
                "can_manage_tenant_settings": TenantUserRole.ROLE_ADMIN in roles,
                "can_manage_requests_settings": can_open_settings,
                "can_manage_wallet_settings": can_open_settings,
                "roles": sorted(list(roles)),
            }
        )


class UserPreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    def _ensure_membership(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return None, Response({"detail": "Unknown tenant"}, status=status.HTTP_404_NOT_FOUND)
        has_membership = TenantMembership.objects.filter(
            tenant=tenant, user=request.user, is_active=True
        ).exists()
        if not has_membership:
            return None, Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        return tenant, None

    def get(self, request):
        tenant, error_response = self._ensure_membership(request)
        if error_response:
            return error_response
        raw_keys = request.query_params.getlist("keys")
        keys: list[str] = []
        for chunk in raw_keys:
            for key in str(chunk or "").split(","):
                normalized = key.strip().lower()
                if normalized:
                    keys.append(normalized)
        if not keys:
            return Response({"items": []})
        rows = TenantUserPreference.objects.filter(
            tenant=tenant,
            user=request.user,
            key__in=keys,
        )
        payload = [{"key": row.key, "value": row.value} for row in rows]
        return Response({"items": payload})

    def put(self, request, key: str):
        tenant, error_response = self._ensure_membership(request)
        if error_response:
            return error_response
        serializer = TenantUserPreferenceSerializer(data={"key": key, "value": request.data.get("value")})
        serializer.is_valid(raise_exception=True)
        pref, _ = TenantUserPreference.objects.update_or_create(
            tenant=tenant,
            user=request.user,
            key=serializer.validated_data["key"],
            defaults={"value": serializer.validated_data["value"]},
        )
        return Response({"key": pref.key, "value": pref.value})

