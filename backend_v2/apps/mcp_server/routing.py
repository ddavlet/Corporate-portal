"""
MCP host routing invariants (api.kolberg.uz).

  /.well-known/oauth-*  → OAuth discovery JSON (ASGI)
  /mcp, /mcp/*          → FastMCP only (protocol + OAuth endpoints)
  /oauth/login/         → Django OTP login (canonical)
  legacy /mcp/.../login → 301 → /oauth/login/ (ASGI, before FastMCP)
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings

# Normalized paths (no trailing slash except "/")
LEGACY_LOGIN_PATHS = frozenset(
    {
        "/mcp/login",
        "/mcp/oauth/login",
        "/oauth/mcp/login",
    }
)


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


def is_legacy_mcp_login_path(path: str) -> bool:
    return path_normalized(path) in LEGACY_LOGIN_PATHS


def is_mcp_protocol_path(path: str) -> bool:
    """All /mcp and /mcp/* go to FastMCP (legacy login excluded earlier in ASGI)."""
    return path == "/mcp" or path.startswith("/mcp/")


def canonical_oauth_login_path() -> str:
    return "/oauth/login/"


async def redirect_legacy_login_to_canonical(scope: dict, send) -> None:
    from apps.mcp_server.oauth.metadata import mcp_oauth_login_url

    target = mcp_oauth_login_url().rstrip("/") + "/"
    qs = scope.get("query_string", b"").decode("latin-1")
    if qs:
        target = f"{target}?{qs}"
    await send(
        {
            "type": "http.response.start",
            "status": 301,
            "headers": [(b"location", target.encode("latin-1"))],
        }
    )
    await send({"type": "http.response.body", "body": b""})
