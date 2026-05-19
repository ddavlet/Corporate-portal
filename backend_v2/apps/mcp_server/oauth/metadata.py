"""
OAuth discovery documents for MCP clients (Claude.ai, etc.).

MCP spec: for server URL https://api.example.com/mcp the authorization *base* is
https://api.example.com — clients fetch metadata from the host root, not /mcp/.
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings


def mcp_public_origin() -> str:
    """Scheme + host for the MCP API host (e.g. https://api.kolberg.uz)."""
    parsed = urlparse(settings.MCP_BASE_URL.rstrip("/"))
    return f"{parsed.scheme}://{parsed.netloc}"


def mcp_oauth_login_url() -> str:
    return settings.MCP_OAUTH_LOGIN_URL


def authorization_server_metadata() -> dict:
    """RFC 8414 — served at /.well-known/oauth-authorization-server on the MCP host."""
    base = settings.MCP_BASE_URL.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "scopes_supported": ["mcp"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256"],
    }


def protected_resource_metadata() -> dict:
    """RFC 9728 — served at /.well-known/oauth-protected-resource on the MCP host."""
    resource = settings.MCP_RESOURCE_URL.rstrip("/")
    issuer = settings.MCP_BASE_URL.rstrip("/")
    return {
        "resource": resource,
        "authorization_servers": [issuer],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


def protected_resource_metadata_url() -> str:
    return f"{mcp_public_origin()}/.well-known/oauth-protected-resource"
