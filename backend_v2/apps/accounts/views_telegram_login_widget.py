import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.telegram_login_widget import (
    TelegramLoginWidgetDataError,
    telegram_user_id_from_login_widget,
    validate_login_widget_auth_data,
)
from apps.tenants.models import TenantMembership
from apps.tenants.permissions import has_effective_module_access

User = get_user_model()
logger = logging.getLogger(__name__)


class TelegramLoginWidgetAuthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"bot_username": (tenant.telegram_bot_username or "").strip()})

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        bot_token = tenant.get_telegram_bot_token()
        if not bot_token:
            return Response(
                {"detail": "Telegram bot is not configured for this tenant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw = request.data.get("auth_data", {})
        if not isinstance(raw, dict):
            return Response({"detail": "auth_data must be an object"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            fields = validate_login_widget_auth_data(raw, bot_token)
            tg_uid = telegram_user_id_from_login_widget(fields)
        except TelegramLoginWidgetDataError as exc:
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
                "Telegram Login Widget auth ambiguous mapping: tenant_id=%s tg_uid=%s sample_user_ids=%s",
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
            return Response(
                {"detail": "You do not have access to the requests module."},
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {"access": str(refresh.access_token), "refresh": str(refresh), "username": user.username},
            status=status.HTTP_200_OK,
        )
