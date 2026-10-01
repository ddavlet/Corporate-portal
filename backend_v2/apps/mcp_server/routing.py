"""
MCP routing on tenant hosts (https://<subdomain>.<BASE_DOMAIN>).

  /.well-known/oauth-*[/mcp] → OAuth discovery JSON for the host (config/asgi.py)
  /mcp/login/                → Django OTP login bound to the tenant
  /mcp, /mcp/*               → MCP app (protocol + OAuth endpoints)
"""

from __future__ import annotations

from django.conf import settings

_WELL_KNOWN_AUTHORIZATION_SERVER = frozenset(
    {"/.well-known/oauth-authorization-server", "/.well-known/oauth-authorization-server/mcp"}
)
_WELL_KNOWN_PROTECTED_RESOURCE = frozenset(
    {"/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"}
)


def path_normalized(path: str) -> str:
    return (path or "/").rstrip("/") or "/"


def mcp_http_enabled() -> bool:
    """HTTP/OAuth MCP surface is off unless MCP_HTTP_ENABLED is set."""
    return bool(getattr(settings, "MCP_HTTP_ENABLED", False))


def is_well_known_authorization_server_path(path: str) -> bool:
    return path_normalized(path) in _WELL_KNOWN_AUTHORIZATION_SERVER


def is_well_known_oauth_path(path: str) -> bool:
    p = path_normalized(path)
    return p in _WELL_KNOWN_AUTHORIZATION_SERVER or p in _WELL_KNOWN_PROTECTED_RESOURCE


def is_mcp_login_path(path: str) -> bool:
    return path_normalized(path) == "/mcp/login"


def is_mcp_protocol_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


def is_tenant_mcp_path(path: str) -> bool:
    return is_mcp_protocol_path(path) or is_well_known_oauth_path(path)
