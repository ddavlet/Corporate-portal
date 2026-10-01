"""Tenant of the current MCP request, resolved from the Host subdomain.

config/asgi.py binds it for every /mcp and /.well-known/oauth-* request on a
tenant host; tools, the OAuth provider and the service-key middleware read it.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class McpTenant:
    id: int
    subdomain: str
    name: str

    @property
    def origin(self) -> str:
        return tenant_origin(self.subdomain)

    @property
    def base_url(self) -> str:
        return f"{self.origin}/mcp"


_current: contextvars.ContextVar[McpTenant | None] = contextvars.ContextVar("mcp_tenant", default=None)


def tenant_origin(subdomain: str) -> str:
    base = (getattr(settings, "BASE_DOMAIN", "") or "localhost").strip(".").lower()
    scheme = "http" if base in ("localhost", "127.0.0.1") else "https"
    return f"{scheme}://{subdomain}.{base}"


def set_current_tenant(tenant: McpTenant | None) -> contextvars.Token:
    return _current.set(tenant)


def reset_current_tenant(token: contextvars.Token) -> None:
    _current.reset(token)


def current_tenant() -> McpTenant:
    tenant = _current.get()
    if tenant is None:
        raise PermissionError("MCP tenant is not resolved for this request")
    return tenant


def resolve_mcp_tenant(host: str) -> McpTenant | None:
    """Active, MCP-enabled tenant for a host like 'lemonfit.kolberg.uz', else None."""
    from apps.tenants.middleware import _get_subdomain
    from apps.tenants.models import Tenant

    sub = _get_subdomain((host or "").lower(), getattr(settings, "BASE_DOMAIN", "") or "")
    if not sub:
        return None
    row = (
        Tenant.objects.filter(subdomain=sub, is_active=True, mcp_enabled=True)
        .values("id", "subdomain", "name")
        .first()
    )
    return McpTenant(**row) if row else None


def origin_allowed(origin: str | None, tenant: McpTenant) -> bool:
    """No Origin (server-to-server) is allowed; a browser Origin must be listed."""
    if not origin:
        return True
    allowed = {o.rstrip("/") for o in settings.MCP_ALLOWED_ORIGINS} | {tenant.origin}
    return origin.rstrip("/") in allowed
