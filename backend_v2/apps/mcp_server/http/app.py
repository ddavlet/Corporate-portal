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

    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
    from apps.mcp_server.server import mcp
    from apps.mcp_server.oauth.provider import KolbergOAuthProvider

    base_url = django_settings.MCP_BASE_URL.rstrip("/")

    mcp.settings.auth = AuthSettings(
        issuer_url=base_url,  # type: ignore[arg-type]
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
    )
    mcp.settings.streamable_http_path = "/"
    mcp._auth_server_provider = KolbergOAuthProvider()

    _mcp_asgi_app = mcp.streamable_http_app()
    return _mcp_asgi_app
