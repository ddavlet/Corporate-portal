"""
JWT validation and access-rights checking for the MCP server.

All functions raise PermissionError on failure so tool handlers can
catch a single exception type and return a clean error message.
"""

from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError


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
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise PermissionError("User not found")

    try:
        tenant = Tenant.objects.get(id=tenant_id, is_active=True)
    except Tenant.DoesNotExist:
        raise PermissionError(f"Tenant {tenant_id} not found or inactive")

    if not TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
        raise PermissionError("User is not an active member of this tenant")

    return user, tenant


def require_module_access(token: str, tenant_id: int, module_key: str):
    """Validate token and ensure the user has access to `module_key` in `tenant_id`.

    Returns (user, tenant). Raises PermissionError on any failure.
    """
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id)

    from apps.tenants.permissions import has_effective_module_access

    if not has_effective_module_access(user=user, tenant=tenant, module_key=module_key):
        raise PermissionError(
            f"Access denied: your role does not allow access to module '{module_key}', "
            "or the module is disabled for this tenant"
        )

    return user, tenant


def require_admin_access(token: str, tenant_id: int):
    """Validate token and ensure the user has the 'admin' role in `tenant_id`.

    Returns (user, tenant). Raises PermissionError on any failure.
    """
    user_id = _decode_token(token)
    user, tenant = _get_user_and_tenant(user_id, tenant_id)

    from apps.tenants.models import TenantUserRole

    if not TenantUserRole.objects.filter(
        tenant=tenant, user=user, role=TenantUserRole.ROLE_ADMIN
    ).exists():
        raise PermissionError("Admin role required for this operation")

    return user, tenant


def require_admin_or_director(token: str, tenant_id: int):
    """Validate token and ensure the user is admin or director in `tenant_id`."""
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
