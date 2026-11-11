"""Portal JWT authentication: MCP connector tokens are never accepted here."""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.tenants.shared_host import is_tenantless_path, resolve_member_tenant

# Set on every JWT issued for an MCP connector (apps/mcp_server/oauth/tokens.py,
# apps/mcp_server/http/service_key.py). Its presence marks a token as MCP-only.
MCP_TENANT_CLAIM = "mcp_tenant_id"


class RejectMcpTokenMixin:
    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)
        if token.get(MCP_TENANT_CLAIM) is not None:
            raise InvalidToken("MCP connector tokens are not accepted by the portal API")
        return token


class PortalJWTAuthentication(RejectMcpTokenMixin, JWTAuthentication):
    pass


class SharedHostPortalJWTAuthentication(PortalJWTAuthentication):
    """
    Portal JWT plus the company check on the shared portal host (``PORTAL_SHARED_HOST``).

    ``SharedHostTenantMiddleware`` leaves ``request.tenant = None`` on the shared host and keeps
    the ``X-Tenant`` value; the tenant is attached here, only for an active member of an active
    tenant. Everything else fails closed:

    - anonymous request or not the shared host: result as in ``PortalJWTAuthentication``
      (``request.tenant`` stays None for anonymous shared-host requests);
    - tenantless path (``SHARED_HOST_TENANTLESS_PREFIXES``): header ignored, no tenant;
    - header with an unknown, inactive or foreign company: 403 ``tenant_forbidden`` (one body);
    - no header: 403 ``tenant_required``.

    Views with their own ``authentication_classes`` never reach this class (audited 2026-11-11):
    n8n integration views (N8nIntegrationTokenOnlyAuthentication; /api/n8n/ is excluded on the
    shared host), telegram_approvals webhook/events (``[]``; excluded paths, tenant comes from
    Approval), investments public payout schedule (``[]``; tenantless path, tenant comes from the
    link token), investments approval callback (``[]``; no URL, called from the webhook only).
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None or not getattr(request._request, "portal_shared_host", False):
            return result
        if is_tenantless_path(request.path or ""):
            return result
        user = result[0]
        header = getattr(request._request, "tenant_header", "") or ""
        if not header:
            raise PermissionDenied(detail={"detail": "Не выбрана компания.", "code": "tenant_required"})
        tenant = resolve_member_tenant(subdomain=header, user=user)
        if tenant is None:
            raise PermissionDenied(detail={"detail": "Нет доступа к компании.", "code": "tenant_forbidden"})
        request._request.tenant = tenant
        return result
