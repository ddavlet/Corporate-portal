"""
OAuth discovery documents for MCP clients (Claude, ChatGPT).

For MCP server URL https://<tenant>.kolberg.uz/mcp the discovery documents are
served from the host root (RFC 8414 / RFC 9728); config/asgi.py passes the
tenant's base URL.
"""

from __future__ import annotations

from django.conf import settings


def mcp_oauth_login_url() -> str:
    """Temporary: removed together with the static login URL (tenant login replaces it)."""
    return settings.MCP_OAUTH_LOGIN_URL


def authorization_server_metadata(base_url: str) -> dict:
    """RFC 8414 — /.well-known/oauth-authorization-server[/mcp] on the tenant host."""
    base = base_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "scopes_supported": ["mcp"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
    }


def protected_resource_metadata(base_url: str) -> dict:
    """RFC 9728 — /.well-known/oauth-protected-resource[/mcp] on the tenant host."""
    base = base_url.rstrip("/")
    return {
        "resource": base,
        "authorization_servers": [base],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


def protected_resource_metadata_url(origin: str) -> str:
    return f"{origin.rstrip('/')}/.well-known/oauth-protected-resource"
