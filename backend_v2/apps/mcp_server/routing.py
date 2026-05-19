"""
MCP host routing invariants (api.kolberg.uz).

  /.well-known/oauth-*  → OAuth discovery JSON (ASGI)
  /mcp, /mcp/*          → FastMCP only (protocol + OAuth endpoints)
  /oauth/login/         → Django OTP login
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings


def path_normalized(path: str) -> str:
    return (path or "/").rstrip("/") or "/"


def mcp_hostname() -> str:
    """Public MCP API host (e.g. api.kolberg.uz), not a tenant subdomain."""
    return (urlparse(settings.MCP_BASE_URL).hostname or "").lower()


def host_no_port(host: str) -> str:
    return (host or "").split(":")[0].lower()


def is_mcp_host(host: str) -> bool:
    name = mcp_hostname()
    return bool(name) and host_no_port(host) == name


def mcp_resource_path_suffix() -> str:
    """Path component of MCP_RESOURCE_URL (e.g. /mcp) for RFC 9728 path-suffixed well-known URIs."""
    path = urlparse(settings.MCP_RESOURCE_URL.rstrip("/")).path or ""
    return path if path and path != "/" else ""


def _well_known_paths() -> frozenset[str]:
    paths = {
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource",
    }
    suffix = mcp_resource_path_suffix()
    if suffix:
        paths.add(f"/.well-known/oauth-authorization-server{suffix}")
        paths.add(f"/.well-known/oauth-protected-resource{suffix}")
    return frozenset(paths)


def is_well_known_oauth_path(path: str) -> bool:
    return path_normalized(path) in _well_known_paths()


def is_well_known_authorization_server_path(path: str) -> bool:
    p = path_normalized(path)
    paths = {"/.well-known/oauth-authorization-server"}
    suffix = mcp_resource_path_suffix()
    if suffix:
        paths.add(f"/.well-known/oauth-authorization-server{suffix}")
    return p in paths


def is_mcp_protocol_path(path: str) -> bool:
    """All /mcp and /mcp/* go to FastMCP."""
    return path == "/mcp" or path.startswith("/mcp/")
