from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.telegram_webapp import TelegramWebAppDataError, telegram_user_id_from_validated, validate_webapp_init_data
from apps.tenants.models import TenantMembership
from apps.tenants.permissions import has_effective_module_access

User = get_user_model()


class TelegramWebAppAuthView(APIView):
    """
    Exchange Telegram.WebApp.initData (validated with tenant bot token) for JWT.
    Tenant from Host (middleware). User must have telegram_from_id or telegram_chat_id
    matching Telegram user id and effective access to module requests.
    """

    permission_classes = [AllowAny]

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

        init_data = str(request.data.get("init_data", "")).strip()
        try:
            flat = validate_webapp_init_data(init_data, bot_token)
            tg_uid = telegram_user_id_from_validated(flat)
        except TelegramWebAppDataError as exc:
            detail = str(exc)
            if detail == "invalid init_data signature":
                detail = (
                    "invalid init_data signature; ensure the tenant Telegram bot token matches "
                    "the bot that opened the Mini App (BotFather API token)."
                )
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list(
            "user_id", flat=True
        )
        user = User.objects.filter(
            Q(telegram_from_id=tg_uid) | Q(telegram_chat_id=tg_uid),
            pk__in=member_ids,
        ).first()

        if not user:
            return Response(
                {"detail": "No user linked to this Telegram account for this organization."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not has_effective_module_access(user=user, tenant=tenant, module_key="requests"):
            return Response(
                {"detail": "You do not have access to the requests module."},
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "username": user.username,
            },
            status=status.HTTP_200_OK,
        )
