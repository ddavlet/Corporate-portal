"""
ASGI config for Kolberg.

MCP HTTP is disabled by default (MCP_HTTP_ENABLED=false). When enabled, on
tenant hosts (https://<subdomain>.<BASE_DOMAIN>):

  /.well-known/oauth-*[/mcp] → per-host OAuth discovery JSON
  /mcp/login/                → Django (OTP login bound to the tenant)
  /mcp, /mcp/*               → MCP app (tenant bound in a contextvar)
  everything else            → Django

Unknown / inactive / MCP-disabled tenant → 404; foreign browser Origin → 403.

Lifespan: proxied to FastMCP only when MCP HTTP is enabled.
"""

from __future__ import annotations

import asyncio
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

_django_app = get_asgi_application()


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


async def _noop_lifespan(scope, receive, send):
    """Complete uvicorn lifespan without starting FastMCP."""
    event = await receive()
    if event["type"] == "lifespan.startup":
        await send({"type": "lifespan.startup.complete"})
        event = await receive()
    if event["type"] == "lifespan.shutdown":
        await send({"type": "lifespan.shutdown.complete"})


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


async def _tenant_mcp(scope, receive, send, path: str) -> None:
    """MCP on a tenant host: resolve tenant, check Origin, bind it, dispatch."""
    from asgiref.sync import sync_to_async

    from apps.mcp_server.routing import (
        is_mcp_login_path,
        is_well_known_authorization_server_path,
        is_well_known_oauth_path,
    )
    from apps.mcp_server.tenant_context import (
        origin_allowed,
        reset_current_tenant,
        resolve_mcp_tenant,
        set_current_tenant,
    )

    headers = dict(scope.get("headers") or [])
    host = headers.get(b"host", b"").decode("latin-1")
    tenant = await sync_to_async(resolve_mcp_tenant, thread_sensitive=True)(host)
    if tenant is None:
        await _send_json(send, {"error": "Not found"}, status=404)
        return

    origin = headers.get(b"origin", b"").decode("latin-1") or None
    if not origin_allowed(origin, tenant):
        await _send_json(send, {"error": "Origin not allowed"}, status=403)
        return

    token = set_current_tenant(tenant)
    try:
        if is_well_known_oauth_path(path):
            from apps.mcp_server.oauth.metadata import (
                authorization_server_metadata,
                protected_resource_metadata,
            )

            if is_well_known_authorization_server_path(path):
                await _send_json(send, authorization_server_metadata(tenant.base_url))
            else:
                await _send_json(send, protected_resource_metadata(tenant.base_url))
            return

        if is_mcp_login_path(path):
            await _django_app(scope, receive, send)
            return

        from apps.mcp_server.http.app import get_mcp_asgi_app

        new_scope = {
            **scope,
            "path": path[4:] or "/",
            "root_path": scope.get("root_path", "") + "/mcp",
        }
        await get_mcp_asgi_app()(new_scope, receive, send)
    finally:
        reset_current_tenant(token)


async def application(scope, receive, send):
    from apps.mcp_server.routing import mcp_http_enabled

    if scope["type"] == "lifespan":
        if mcp_http_enabled():
            await _proxy_lifespan_to_mcp(scope, receive, send)
        else:
            await _noop_lifespan(scope, receive, send)
        return

    if scope["type"] != "http":
        await _django_app(scope, receive, send)
        return

    if not mcp_http_enabled():
        await _django_app(scope, receive, send)
        return

    path = scope.get("path", "")

    from apps.mcp_server.routing import is_tenant_mcp_path

    if is_tenant_mcp_path(path):
        await _tenant_mcp(scope, receive, send, path)
        return

    await _django_app(scope, receive, send)
