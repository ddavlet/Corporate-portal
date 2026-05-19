"""
MCP host routing invariants (api.kolberg.uz).

  /.well-known/oauth-*  → OAuth discovery JSON (ASGI)
  /mcp, /mcp/*          → FastMCP only (protocol + OAuth endpoints)
  /oauth/login/         → Django OTP login (canonical)
  legacy /mcp/.../login → 301 → /oauth/login/ (ASGI, before FastMCP)
"""

from __future__ import annotations

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


def is_well_known_oauth_path(path: str) -> bool:
    return path_normalized(path) in (
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource",
    )


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
