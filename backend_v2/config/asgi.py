"""
ASGI config for Kolberg.

MCP host (api.kolberg.uz) routing — see apps.mcp_server.routing:
  /.well-known/oauth-*  → JSON metadata
  legacy /mcp/.../login → 301 → /oauth/login/
  /mcp, /mcp/*          → FastMCP
  /oauth/login/         → Django (OTP)
  everything else       → Django

Lifespan: proxied to FastMCP (StreamableHttpSessionManager TaskGroup).
"""

from __future__ import annotations

import asyncio
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

_django_app = get_asgi_application()

_WELL_KNOWN_AUTH = "/.well-known/oauth-authorization-server"


async def _send_json(send, payload: dict, *, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


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


async def application(scope, receive, send):
    if scope["type"] == "lifespan":
        await _proxy_lifespan_to_mcp(scope, receive, send)
        return

    if scope["type"] != "http":
        await _django_app(scope, receive, send)
        return

    path = scope.get("path", "")

    from apps.mcp_server.routing import (
        is_legacy_mcp_login_path,
        is_mcp_protocol_path,
        is_well_known_oauth_path,
        path_normalized,
        redirect_legacy_login_to_canonical,
    )

    if is_well_known_oauth_path(path):
        from apps.mcp_server.oauth.metadata import (
            authorization_server_metadata,
            protected_resource_metadata,
        )

        if path_normalized(path) == _WELL_KNOWN_AUTH:
            await _send_json(send, authorization_server_metadata())
        else:
            await _send_json(send, protected_resource_metadata())
        return

    if is_legacy_mcp_login_path(path):
        await redirect_legacy_login_to_canonical(scope, send)
        return

    if is_mcp_protocol_path(path):
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
