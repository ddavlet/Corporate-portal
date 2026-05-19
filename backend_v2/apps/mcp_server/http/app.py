"""
Creates the FastMCP ASGI application with OAuth 2.0 authentication.

Mounted at /mcp/ in config/asgi.py. The ASGI router strips the /mcp prefix
so FastMCP sees paths relative to its root:
  /mcp/           → FastMCP handles MCP protocol
  /mcp/authorize  → FastMCP OAuth authorize endpoint
  /mcp/token      → FastMCP OAuth token endpoint
  /mcp/register   → FastMCP dynamic client registration
  /mcp/.well-known/... → OAuth metadata discovery

/mcp/login/ is handled by Django (see config/urls.py).
"""

from __future__ import annotations

from django.conf import settings as django_settings

_mcp_asgi_app = None


def get_mcp_asgi_app():
    """Return the FastMCP ASGI app (lazy singleton)."""
    global _mcp_asgi_app
    if _mcp_asgi_app is not None:
        return _mcp_asgi_app

    from urllib.parse import urlparse
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
    from mcp.server.transport_security import TransportSecuritySettings
    from apps.mcp_server.server import mcp
    from apps.mcp_server.oauth.provider import KolbergOAuthProvider

    base_url = django_settings.MCP_BASE_URL.rstrip("/")
    parsed = urlparse(base_url)
    public_host = parsed.hostname  # e.g. "api.kolberg.uz"
    public_origin = f"{parsed.scheme}://{parsed.netloc}"  # e.g. "https://api.kolberg.uz"

    mcp.settings.auth = AuthSettings(
        issuer_url=base_url,  # type: ignore[arg-type]
        resource_server_url=None,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
    )
    # FastMCP defaults to localhost-only DNS rebinding protection when host="127.0.0.1".
    # Override with the actual public host so MCP clients can connect.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host],
        allowed_origins=[public_origin],
    )
    mcp.settings.streamable_http_path = "/"
    # Stateless mode: no session state stored per-worker, so requests can
    # hit any gunicorn worker without losing session context.
    mcp.settings.stateless_http = True
    mcp._auth_server_provider = KolbergOAuthProvider()

    _mcp_asgi_app = mcp.streamable_http_app()
    return _mcp_asgi_app
