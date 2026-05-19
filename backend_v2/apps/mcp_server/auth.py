"""
JWT validation and access-rights checking for the MCP server.

Supports two modes:
  - stdio: token read from KOLBERG_JWT_TOKEN environment variable.
  - HTTP/OAuth: token set per-request via _request_token contextvar
    (populated by KolbergOAuthProvider.load_access_token).

All public functions raise PermissionError on failure so tool handlers can
catch a single exception type and return a clean error message.
"""

from __future__ import annotations

import contextvars
import os

from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError

_ENV_VAR = "KOLBERG_JWT_TOKEN"

# Set per-request in HTTP mode by the OAuth provider's load_access_token().
_request_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mcp_request_token", default=""
)


def set_request_token(token: str) -> None:
    """Set the JWT token for the current async request context (HTTP mode)."""
    _request_token.set(token)


def _get_token() -> str:
    """Return the JWT token for the current context.

    HTTP mode: reads from _request_token (set by OAuth provider per-request).
    stdio mode: reads from KOLBERG_JWT_TOKEN environment variable.
    """
    token = _request_token.get("").strip()
    if not token:
        token = os.environ.get(_ENV_VAR, "").strip()
    if not token:
        raise PermissionError(
            "No authentication token available. "
            f"stdio mode: set {_ENV_VAR} env var. "
            "HTTP mode: authenticate via OAuth at /mcp/authorize."
        )
    return token


def _decode_token(token: str) -> int:
    """Return user_id from a valid JWT access token, or raise PermissionError."""
    try:
        payload = AccessToken(token)
        return int(payload["user_id"])
    except (TokenError, KeyError, ValueError) as exc:
        raise PermissionError(f"Invalid or expired token: {exc}") from exc


def _get_user_and_tenant(user_id: int, tenant_id: int):
    from apps.accounts.models import User
    from apps.tenants.models import Tenant, TenantMembership

    try:
        user = User.objects.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        raise PermissionError("User not found or deactivated")

    try:
        tenant = Tenant.objects.get(id=tenant_id, is_active=True)
    except Tenant.DoesNotExist:
        raise PermissionError(f"Tenant {tenant_id} not found or inactive")

    if not tenant.mcp_enabled:
        raise PermissionError(
            f"MCP access is not enabled for tenant '{tenant.subdomain}'. "
            "Ask your administrator to enable it in tenant settings."
        )

    if not TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
        raise PermissionError("User is not an active member of this tenant")

    return user, tenant


def require_module_access(tenant_id: int, module_key: str):
    """Validate the env token and ensure the user has access to `module_key`.

    Returns (user, tenant). Raises PermissionError on any failure.
    """
    token = _get_token()
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id)

    from apps.tenants.permissions import has_effective_module_access

    if not has_effective_module_access(user=user, tenant=tenant, module_key=module_key):
        raise PermissionError(
            f"Access denied: your role does not allow access to module '{module_key}', "
            "or the module is disabled for this tenant"
        )

    return user, tenant


def require_admin_access(tenant_id: int):
    """Validate the env token and ensure the user has the 'admin' role.

    Returns (user, tenant). Raises PermissionError on any failure.
    """
    token = _get_token()
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id)

    from apps.tenants.models import TenantUserRole

    if not TenantUserRole.objects.filter(
        tenant=tenant, user=user, role=TenantUserRole.ROLE_ADMIN
    ).exists():
        raise PermissionError("Admin role required for this operation")

    return user, tenant


def require_admin_or_director(tenant_id: int):
    """Validate the env token and ensure the user is admin or director."""
    token = _get_token()
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id)

    from apps.tenants.models import TenantUserRole

    if not TenantUserRole.objects.filter(
        tenant=tenant,
        user=user,
        role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR],
    ).exists():
        raise PermissionError("Admin or Director role required for this operation")

    return user, tenant
