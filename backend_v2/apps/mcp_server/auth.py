"""
JWT validation and access-rights checking for the MCP server.

The token is set per request via the _request_token contextvar (populated by
KolbergOAuthProvider.load_access_token, or by the service-key middleware) and is
valid only for the tenant of the request host (claim mcp_tenant_id).

All public functions raise PermissionError on failure so tool handlers can
catch a single exception type and return a clean error message.
"""

from __future__ import annotations

import contextvars

from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError

# Set per request by the OAuth provider's load_access_token().
_request_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mcp_request_token", default=""
)


def set_request_token(token: str) -> None:
    """Set the JWT token for the current async request context."""
    _request_token.set(token)


def _get_token() -> str:
    """JWT of the current request (set by the OAuth provider / service-key middleware)."""
    token = _request_token.get("").strip()
    if not token:
        raise PermissionError("Not authenticated: connect this MCP server via OAuth.")
    return token


def _decode_token(token: str) -> int:
    """user_id from a valid MCP access token bound to the current tenant, else PermissionError."""
    from apps.accounts.authentication import MCP_TENANT_CLAIM
    from apps.mcp_server.tenant_context import current_tenant

    try:
        payload = AccessToken(token)
        user_id = int(payload["user_id"])
        token_tenant = payload.get(MCP_TENANT_CLAIM)
    except (TokenError, KeyError, ValueError) as exc:
        raise PermissionError(f"Invalid or expired token: {exc}") from exc
    if token_tenant is None or int(token_tenant) != current_tenant().id:
        raise PermissionError("Token is not valid for this company")
    return user_id


def _is_service_claim(token: str) -> bool:
    """True if `token` was minted by the service-key middleware (custom `svc` claim)."""
    try:
        return bool(AccessToken(token).payload.get("svc", False))
    except TokenError:
        return False


def _get_user_and_tenant(user_id: int, tenant_id: int, *, service_mode: bool = False):
    try:
        return _get_user_and_tenant_unchecked(user_id, tenant_id)
    except PermissionError:
        if service_mode:
            raise PermissionError(
                f"Access denied: tenant {tenant_id} is not accessible with this key"
            )
        raise


def _get_user_and_tenant_unchecked(user_id: int, tenant_id: int):
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
    user, tenant = _get_user_and_tenant(user_id, tenant_id, service_mode=_is_service_claim(token))

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
    user, tenant = _get_user_and_tenant(user_id, tenant_id, service_mode=_is_service_claim(token))

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
    user, tenant = _get_user_and_tenant(user_id, tenant_id, service_mode=_is_service_claim(token))

    from apps.tenants.models import TenantUserRole

    if not TenantUserRole.objects.filter(
        tenant=tenant,
        user=user,
        role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR],
    ).exists():
        raise PermissionError("Admin or Director role required for this operation")

    return user, tenant
