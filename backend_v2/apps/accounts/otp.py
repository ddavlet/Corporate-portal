"""
Shared OTP send/verify helpers (portal API and MCP OAuth login).
"""

from __future__ import annotations

import os
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import OtpChallenge, User
from apps.modules.telegram_approvals.services import get_tenant_bot_token, post_messaging_gateway
from apps.tenants.models import Tenant, TenantMembership

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60"))
OTP_REQUEST_WINDOW_SECONDS = int(os.getenv("OTP_REQUEST_WINDOW_SECONDS", "600"))
OTP_REQUEST_MAX_IN_WINDOW = int(os.getenv("OTP_REQUEST_MAX_IN_WINDOW", "3"))
OTP_DIGITS = int(os.getenv("OTP_DIGITS", "6"))
OTP_HASH_SALT = os.getenv("OTP_HASH_SALT", settings.SECRET_KEY)


class OtpError(Exception):
    """User-facing OTP failure (safe to show in HTML or API responses)."""


def _otp_cache_key(tenant_id: int, username: str, ip: str) -> str:
    return f"otp:req:{tenant_id}:{username.lower()}:{ip or 'na'}"


def _hash_code(code: str) -> str:
    return make_password(f"{OTP_HASH_SALT}:{code}")


def _check_code(code: str, code_hash: str) -> bool:
    return check_password(f"{OTP_HASH_SALT}:{code}", code_hash)


def _send_otp_via_gateway(*, tenant: Tenant, bot_token: str, chat_id: int, text: str) -> None:
    payload = {
        "action": "send",
        "bot_token": bot_token,
        "tenant_id": str(tenant.id),
        "recipient_id": str(chat_id),
        "text": text,
        "format": "html",
    }
    data = post_messaging_gateway(tenant=tenant, payload=payload)
    if data is None:
        raise OtpError("Не удалось отправить OTP (messaging gateway).")
    if isinstance(data, dict) and data.get("ok") is True:
        return
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("description") or data
        raise OtpError(f"Не удалось отправить OTP: {detail}")
    raise OtpError(f"Не удалось отправить OTP: {data}")


def resolve_mcp_otp_tenant(user: User) -> Tenant:
    """Pick tenant for MCP login OTP (MCP host has no request.tenant)."""
    memberships = (
        TenantMembership.objects.filter(
            user=user,
            is_active=True,
            tenant__is_active=True,
            tenant__mcp_enabled=True,
            tenant__telegram_otp_enabled=True,
        )
        .select_related("tenant")
        .order_by("tenant__name")
    )
    tenants = [m.tenant for m in memberships]
    if not tenants:
        raise OtpError(
            "Для этого пользователя нет организации с включёнными MCP и OTP в Telegram."
        )
    return tenants[0]


def send_otp(*, user: User, tenant: Tenant | None = None, ip: str = "") -> None:
    """Create OTP challenge and deliver code via tenant Telegram bot."""
    if tenant is None:
        tenant = resolve_mcp_otp_tenant(user)

    username = user.username
    key = _otp_cache_key(tenant.id, username, ip)
    if cache.get(key):
        raise OtpError("Повторите запрос позже.")

    window_start = timezone.now() - timedelta(seconds=OTP_REQUEST_WINDOW_SECONDS)
    recent_count = OtpChallenge.objects.filter(
        tenant=tenant, user=user, created_at__gte=window_start
    ).count()
    if recent_count >= OTP_REQUEST_MAX_IN_WINDOW:
        raise OtpError("Слишком много запросов. Попробуйте позже.")

    if not tenant.telegram_otp_enabled:
        raise OtpError("OTP для этой организации отключён.")

    bot_token = get_tenant_bot_token(tenant)
    if not bot_token or not user.telegram_chat_id:
        raise OtpError("OTP недоступен: нет Telegram chat_id или бота организации.")

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
    _send_otp_via_gateway(
        tenant=tenant,
        bot_token=bot_token,
        chat_id=int(user.telegram_chat_id),
        text=message,
    )
    cache.set(key, "1", timeout=OTP_RESEND_COOLDOWN_SECONDS)


def verify_otp(*, user: User, code: str, tenant: Tenant | None = None) -> None:
    """Validate OTP and mark challenge consumed."""
    if tenant is None:
        tenant = resolve_mcp_otp_tenant(user)

    code = (code or "").strip()
    if not code:
        raise OtpError("Неверный или истёкший код.")

    challenge = (
        OtpChallenge.objects.filter(
            user=user, tenant=tenant, consumed_at__isnull=True
        )
        .order_by("-created_at")
        .first()
    )
    if not challenge:
        raise OtpError("Неверный или истёкший код.")
    if challenge.expires_at < timezone.now():
        raise OtpError("Срок действия кода истёк.")
    if challenge.attempts >= OTP_MAX_ATTEMPTS:
        raise OtpError("Превышено число попыток. Запросите новый код.")

    if not _check_code(code, challenge.code_hash):
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        raise OtpError("Неверный или истёкший код.")

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])
