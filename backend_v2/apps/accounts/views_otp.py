import hashlib
import os
import random
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import OtpChallenge
from apps.tenants.integration_settings import get_notes_integration_settings
from apps.tenants.models import TenantMembership, TenantUserRole

User = get_user_model()

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60"))
OTP_REQUEST_WINDOW_SECONDS = int(os.getenv("OTP_REQUEST_WINDOW_SECONDS", "600"))
OTP_REQUEST_MAX_IN_WINDOW = int(os.getenv("OTP_REQUEST_MAX_IN_WINDOW", "3"))
OTP_DIGITS = int(os.getenv("OTP_DIGITS", "6"))
OTP_HASH_SALT = os.getenv("OTP_HASH_SALT", settings.SECRET_KEY)


def _public_ok_message():
    return {"detail": "Если пользователь доступен для OTP, код будет отправлен."}


def _tenant_user(tenant, username):
    user = User.objects.filter(username=username).first()
    if not user:
        return None
    has_membership = TenantMembership.objects.filter(tenant=tenant, user=user, is_active=True).exists()
    return user if has_membership else None


def _otp_cache_key(tenant_id: int, username: str, ip: str):
    return f"otp:req:{tenant_id}:{username.lower()}:{ip or 'na'}"


def _hash_code(code: str):
    raw = f"{OTP_HASH_SALT}:{code}"
    return make_password(raw)


def _check_code(code: str, code_hash: str):
    raw = f"{OTP_HASH_SALT}:{code}"
    return check_password(raw, code_hash)


def _send_telegram_message(*, tenant, bot_token: str, chat_id: int, text: str):
    base_url = get_notes_integration_settings(tenant=tenant).telegram_api_base_url
    try:
        resp = requests.post(
            f"{base_url}/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.ok, resp.status_code, (resp.text or "")
    except requests.RequestException as exc:
        return False, None, str(exc)


def _notify_tenant_admins(*, tenant, bot_token: str, text: str) -> None:
    """
    Best-effort diagnostics to tenant admins.
    Uses the same per-tenant bot token.
    """
    if not tenant or not bot_token:
        return

    admin_user_ids = (
        TenantUserRole.objects.filter(tenant=tenant, role=TenantUserRole.ROLE_ADMIN)
        .values_list("user_id", flat=True)
        .distinct()
    )
    # Ensure we only notify active members with a telegram_chat_id.
    admins = (
        User.objects.filter(id__in=admin_user_ids)
        .filter(telegram_chat_id__isnull=False)
        .filter(
            id__in=TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
        )
    )

    clipped = (text or "").strip()
    if len(clipped) > 3500:
        clipped = clipped[:3500] + "…"

    for admin in admins.iterator():
        try:
            _send_telegram_message(tenant=tenant, bot_token=bot_token, chat_id=int(admin.telegram_chat_id), text=clipped)
        except Exception:
            # Do not let diagnostics break auth flow.
            pass


class OtpRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        username = str(request.data.get("username", "")).strip()
        ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or ""

        if not tenant or not username:
            return Response(_public_ok_message(), status=status.HTTP_200_OK)

        key = _otp_cache_key(tenant.id, username, ip)
        if cache.get(key):
            return Response({"detail": "Повторите запрос позже."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        window_start = timezone.now() - timedelta(seconds=OTP_REQUEST_WINDOW_SECONDS)
        recent_count = OtpChallenge.objects.filter(
            tenant=tenant, user__username=username, created_at__gte=window_start
        ).count()
        if recent_count >= OTP_REQUEST_MAX_IN_WINDOW:
            return Response({"detail": "Слишком много запросов. Попробуйте позже."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        user = _tenant_user(tenant, username)
        if not user:
            return Response(_public_ok_message(), status=status.HTTP_200_OK)
        if not tenant.telegram_otp_enabled:
            return Response({"detail": "OTP для этого тенанта отключен."}, status=status.HTTP_400_BAD_REQUEST)

        bot_token = tenant.get_telegram_bot_token()
        if not bot_token or not user.telegram_chat_id:
            return Response({"detail": "OTP недоступен для этого пользователя."}, status=status.HTTP_400_BAD_REQUEST)

        code = "".join(str(random.randint(0, 9)) for _ in range(OTP_DIGITS))
        expires_at = timezone.now() + timedelta(seconds=OTP_TTL_SECONDS)
        OtpChallenge.objects.create(
            user=user,
            tenant=tenant,
            code_hash=_hash_code(code),
            expires_at=expires_at,
            created_ip=ip or None,
        )

        message = (
            "Код подтверждения входа:\n"
            f"<code>{code}</code>\n\n"
            "Срок действия — 5 минут."
        )
        sent, tg_status, tg_body = _send_telegram_message(
            tenant=tenant,
            bot_token=bot_token,
            chat_id=user.telegram_chat_id,
            text=message,
        )
        cache.set(key, "1", timeout=OTP_RESEND_COOLDOWN_SECONDS)

        if not sent:
            _notify_tenant_admins(
                tenant=tenant,
                bot_token=bot_token,
                text=(
                    "⚠️ OTP: не удалось отправить сообщение пользователю.\n"
                    f"tenant={tenant.subdomain}\n"
                    f"username={username}\n"
                    f"chat_id={user.telegram_chat_id}\n"
                    f"telegram_status={tg_status}\n"
                    f"telegram_body={tg_body}"
                ),
            )
            return Response({"detail": "Не удалось отправить OTP. Попробуйте позже."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(_public_ok_message(), status=status.HTTP_200_OK)


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        username = str(request.data.get("username", "")).strip()
        code = str(request.data.get("code", "")).strip()
        if not tenant or not username or not code:
            return Response({"detail": "Неверный код."}, status=status.HTTP_400_BAD_REQUEST)

        user = _tenant_user(tenant, username)
        if not user:
            return Response({"detail": "Неверный код."}, status=status.HTTP_400_BAD_REQUEST)

        challenge = (
            OtpChallenge.objects.filter(user=user, tenant=tenant, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if not challenge:
            return Response({"detail": "Неверный код."}, status=status.HTTP_400_BAD_REQUEST)
        if challenge.expires_at < timezone.now():
            return Response({"detail": "Срок действия кода истек."}, status=status.HTTP_400_BAD_REQUEST)
        if challenge.attempts >= OTP_MAX_ATTEMPTS:
            return Response({"detail": "Превышено число попыток. Запросите новый код."}, status=status.HTTP_400_BAD_REQUEST)

        if not _check_code(code, challenge.code_hash):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            return Response({"detail": "Неверный код."}, status=status.HTTP_400_BAD_REQUEST)

        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {"access": str(refresh.access_token), "refresh": str(refresh)},
            status=status.HTTP_200_OK,
        )
