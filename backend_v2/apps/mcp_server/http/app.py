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

# Never a real host: the SDK requires an https issuer, but discovery for clients
# is answered per tenant host by config/asgi.py.
_PLACEHOLDER_URL = "https://mcp-placeholder.invalid/mcp"


def build_auth_settings():
    """SDK auth settings shared by all tenant hosts.

    validate_token_resource=False: the SDK compares tokens with ONE resource_server_url,
    but this app serves many hosts. Tokens are bound to their host by our own check
    instead (authorize rejects a foreign RFC 8707 resource; mcp_tenant_id is matched
    against the host tenant on every request — apps/mcp_server/auth.py). SDK 3.0 turns
    the check on by default, which would reject every token against the placeholder.
    """
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

    return AuthSettings(
        issuer_url=_PLACEHOLDER_URL,  # type: ignore[arg-type]
        resource_server_url=_PLACEHOLDER_URL,  # type: ignore[arg-type]
        validate_token_resource=False,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
    )


def get_mcp_asgi_app():
    """Return the MCP ASGI app (lazy singleton)."""
    global _mcp_asgi_app
    if _mcp_asgi_app is not None:
        return _mcp_asgi_app

    from mcp.server.auth.provider import ProviderTokenVerifier
    from mcp.server.transport_security import TransportSecuritySettings

    from apps.mcp_server.http.middleware import with_mcp_resource_metadata
    from apps.mcp_server.http.service_key import with_service_key_auth
    from apps.mcp_server.oauth.provider import KolbergOAuthProvider
    from apps.mcp_server.server import mcp

    mcp.settings.auth = build_auth_settings()
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
