import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.telegram_oidc import (
    TelegramOidcError,
    exchange_code_for_tokens,
    get_telegram_oidc_discovery,
    telegram_user_id_from_id_token,
    validate_telegram_id_token,
)
from apps.tenants.models import TenantMembership
from apps.tenants.permissions import has_effective_module_access

User = get_user_model()
logger = logging.getLogger(__name__)


class TelegramOidcConfigView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        cfg = getattr(tenant, "integration_config", None)
        client_id = str(getattr(cfg, "telegram_oidc_client_id", "") or "").strip()
        redirect_uri = str(getattr(cfg, "telegram_oidc_redirect_uri", "") or "").strip()
        if not client_id or not redirect_uri:
            return Response({"detail": "Telegram OIDC is not configured for this tenant."}, status=status.HTTP_400_BAD_REQUEST)

        discovery = get_telegram_oidc_discovery()
        return Response(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "authorization_endpoint": discovery.authorization_endpoint,
                "scope": "openid profile telegram:bot_access",
            }
        )


class TelegramOidcExchangeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)
        cfg = getattr(tenant, "integration_config", None)
        client_id = str(getattr(cfg, "telegram_oidc_client_id", "") or "").strip()
        client_secret = str(getattr(cfg, "get_telegram_oidc_client_secret", lambda: "")()).strip()
        configured_redirect_uri = str(getattr(cfg, "telegram_oidc_redirect_uri", "") or "").strip()
        if not client_id or not client_secret or not configured_redirect_uri:
            return Response({"detail": "Telegram OIDC is not configured for this tenant."}, status=status.HTTP_400_BAD_REQUEST)

        code = str(request.data.get("code", "")).strip()
        code_verifier = str(request.data.get("code_verifier", "")).strip()
        redirect_uri = str(request.data.get("redirect_uri", "")).strip()
        nonce = str(request.data.get("nonce", "")).strip() or None
        if not code or not code_verifier or not redirect_uri:
            return Response({"detail": "code, code_verifier and redirect_uri are required."}, status=status.HTTP_400_BAD_REQUEST)
        if redirect_uri != configured_redirect_uri:
            return Response({"detail": "redirect_uri mismatch."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            discovery = get_telegram_oidc_discovery()
            tokens = exchange_code_for_tokens(
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
                client_id=client_id,
                client_secret=client_secret,
                token_endpoint=discovery.token_endpoint,
            )
            id_token = str(tokens.get("id_token", "")).strip()
            if not id_token:
                raise TelegramOidcError("missing id_token")
            claims = validate_telegram_id_token(
                id_token=id_token,
                client_id=client_id,
                jwks_uri=discovery.jwks_uri,
                expected_issuer=discovery.issuer,
                expected_nonce=nonce,
            )
            tg_uid = telegram_user_id_from_id_token(claims)
        except TelegramOidcError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
        matches = list(
            User.objects.filter(Q(telegram_from_id=tg_uid) | Q(telegram_chat_id=tg_uid), pk__in=member_ids).order_by("id")[:2]
        )
        if not matches:
            return Response(
                {"detail": "No user linked to this Telegram account for this organization."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if len(matches) > 1:
            logger.warning(
                "Telegram OIDC auth ambiguous mapping: tenant_id=%s tg_uid=%s sample_user_ids=%s",
                getattr(tenant, "id", None),
                tg_uid,
                [u.id for u in matches],
            )
            return Response(
                {"detail": "Telegram account is linked to multiple users in this organization."},
                status=status.HTTP_409_CONFLICT,
            )

        user = matches[0]
        if not has_effective_module_access(user=user, tenant=tenant, module_key="requests"):
            return Response({"detail": "You do not have access to the requests module."}, status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "username": user.username})
