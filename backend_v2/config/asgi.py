"""
ASGI config for Kolberg.

Request routing:
  /.well-known/oauth-*  → Django (MCP OAuth discovery at authorization base URL)
  /oauth/mcp/login/     → Django (OTP login for MCP OAuth)
  /mcp/login/           → Django (legacy redirect → /oauth/mcp/login/)
  /mcp/*                → FastMCP (OAuth protocol + MCP Streamable HTTP)
  everything else       → Django

Lifespan:
  FastMCP's StreamableHttpSessionManager requires a lifespan startup
  to initialise its anyio TaskGroup. Django does not support lifespan,
  so we proxy the lifespan protocol only to FastMCP.
"""

import asyncio
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

_django_app = get_asgi_application()


async def _proxy_lifespan_to_mcp(scope, receive, send):
    """Receive lifespan events from uvicorn and forward them to FastMCP."""
    from apps.mcp_server.http.app import get_mcp_asgi_app

    mcp_app = get_mcp_asgi_app()

    to_mcp: asyncio.Queue = asyncio.Queue()
    from_mcp: asyncio.Queue = asyncio.Queue()

    async def mcp_receive():
        return await to_mcp.get()

    async def mcp_send(message):
        await from_mcp.put(message)

    mcp_task = asyncio.ensure_future(
        mcp_app({"type": "lifespan", "asgi": scope.get("asgi", {})}, mcp_receive, mcp_send)
    )

    event = await receive()
    assert event["type"] == "lifespan.startup"
    await to_mcp.put({"type": "lifespan.startup"})

    response = await from_mcp.get()
    if response["type"] == "lifespan.startup.failed":
        await send(response)
        return
    await send({"type": "lifespan.startup.complete"})

    event = await receive()
    assert event["type"] == "lifespan.shutdown"
    await to_mcp.put({"type": "lifespan.shutdown"})

    await from_mcp.get()
    await send({"type": "lifespan.shutdown.complete"})
    await mcp_task


def _is_mcp_protocol_path(path: str) -> bool:
    """FastMCP handles /mcp and /mcp/* except legacy login redirect."""
    if path == "/mcp":
        return True
    if not path.startswith("/mcp/"):
        return False
    if path == "/mcp/login" or path.startswith("/mcp/login/"):
        return False
    return True


async def application(scope, receive, send):
    if scope["type"] == "lifespan":
        await _proxy_lifespan_to_mcp(scope, receive, send)
        return

    path = scope.get("path", "")

    if scope["type"] == "http" and _is_mcp_protocol_path(path):
        from apps.mcp_server.http.app import get_mcp_asgi_app

        new_path = path[4:] or "/"
        new_scope = {
            **scope,
            "path": new_path,
            "root_path": scope.get("root_path", "") + "/mcp",
        }
        await get_mcp_asgi_app()(new_scope, receive, send)
        return

    await _django_app(scope, receive, send)
