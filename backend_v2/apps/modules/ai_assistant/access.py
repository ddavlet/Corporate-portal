import logging
from dataclasses import dataclass

from django.contrib.auth import get_user_model

from apps.tenants.models import TenantModuleConfig, TenantUserRole

from .config import ALLOWED_ROLES
from .registry import MODULE_KEY

logger = logging.getLogger(__name__)

REASON_OK = "ok"
REASON_NOT_MEMBER = "not_member"
REASON_AMBIGUOUS = "ambiguous_user"
REASON_ROLE_NOT_ALLOWED = "role_not_allowed"


@dataclass(frozen=True)
class AccessResult:
    user: object | None
    roles: frozenset
    reason: str


def assistant_enabled(tenant) -> bool:
    if not tenant.mcp_enabled:
        return False
    return TenantModuleConfig.objects.filter(tenant=tenant, module_key=MODULE_KEY, is_enabled=True).exists()


def _active_members(tenant, telegram_user_id: int) -> list:
    User = get_user_model()
    return list(
        User.objects.filter(
            is_active=True,
            telegram_from_id=telegram_user_id,
            tenantmembership__tenant=tenant,
            tenantmembership__is_active=True,
        ).distinct()[:2]
    )


def _roles_of(tenant, user) -> frozenset:
    return frozenset(
        TenantUserRole.objects.filter(tenant=tenant, user=user).values_list("role", flat=True)
    )


def resolve_assistant_user(tenant, telegram_user_id: int) -> AccessResult:
    candidates = _active_members(tenant, telegram_user_id)
    if not candidates:
        return AccessResult(user=None, roles=frozenset(), reason=REASON_NOT_MEMBER)
    if len(candidates) > 1:
        logger.warning(
            "ai_assistant: several active users share telegram_from_id=%s in tenant=%s",
            telegram_user_id,
            tenant.pk,
        )
        return AccessResult(user=None, roles=frozenset(), reason=REASON_AMBIGUOUS)
    user = candidates[0]
    roles = _roles_of(tenant, user)
    if not (roles & ALLOWED_ROLES):
        return AccessResult(user=user, roles=roles, reason=REASON_ROLE_NOT_ALLOWED)
    return AccessResult(user=user, roles=roles, reason=REASON_OK)


def portal_identity(tenant, telegram_user_id: int):
    """Active member (or None) and comma-joined sorted roles; used to label `member` nodes."""
    candidates = _active_members(tenant, telegram_user_id)
    if len(candidates) != 1:
        return None, ""
    user = candidates[0]
    return user, ",".join(sorted(_roles_of(tenant, user)))
