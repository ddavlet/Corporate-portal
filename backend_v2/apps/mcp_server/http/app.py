"""
Creates the MCP ASGI application (streamable HTTP + OAuth) shared by all tenant hosts.

config/asgi.py mounts it under /mcp/ on https://<tenant>.<BASE_DOMAIN> after
binding the tenant; paths below are relative to /mcp:
  /           → MCP protocol
  /authorize  → OAuth authorize (redirects to /mcp/login/, Django)
  /token      → OAuth token
  /register   → dynamic client registration

Per-host discovery (/.well-known/oauth-* and /mcp/.well-known/*) is served by
config/asgi.py; the SDK's issuer_url below is a placeholder that no client sees.
Host and Origin are validated by config/asgi.py (the SDK only supports exact hosts).
"""

from __future__ import annotations

_mcp_asgi_app = None


def get_mcp_asgi_app():
    """Return the MCP ASGI app (lazy singleton)."""
    global _mcp_asgi_app
    if _mcp_asgi_app is not None:
        return _mcp_asgi_app

    from mcp.server.auth.provider import ProviderTokenVerifier
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
    from mcp.server.transport_security import TransportSecuritySettings

    from apps.mcp_server.http.middleware import with_mcp_resource_metadata
    from apps.mcp_server.http.service_key import with_service_key_auth
    from apps.mcp_server.oauth.provider import KolbergOAuthProvider
    from apps.mcp_server.server import mcp

    # Never a real host: the SDK requires an https issuer, but discovery for clients
    # is answered per tenant host by config/asgi.py.
    placeholder = "https://mcp-placeholder.invalid/mcp"
    mcp.settings.auth = AuthSettings(
        issuer_url=placeholder,  # type: ignore[arg-type]
        resource_server_url=placeholder,  # type: ignore[arg-type]
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
    )
    provider = KolbergOAuthProvider()
    mcp._auth_server_provider = provider
    mcp._token_verifier = ProviderTokenVerifier(provider)

    _mcp_asgi_app = with_mcp_resource_metadata(with_service_key_auth(
        mcp.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
    ))
    return _mcp_asgi_app
