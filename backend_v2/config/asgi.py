"""
ASGI config for Kolberg.

Request routing:
  /mcp/login/  → Django (MCP OAuth login page)
  /mcp/*       → FastMCP (OAuth protocol + MCP protocol)
  everything else → Django
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

_django_app = get_asgi_application()


async def application(scope, receive, send):
    path = scope.get("path", "")

    if scope["type"] == "http" and path.startswith("/mcp/") and not path.startswith("/mcp/login"):
        from apps.mcp_server.http.app import get_mcp_asgi_app

        # Strip /mcp prefix: FastMCP routes are relative to its own root.
        new_path = path[4:] or "/"
        new_scope = {
            **scope,
            "path": new_path,
            "root_path": scope.get("root_path", "") + "/mcp",
        }
        await get_mcp_asgi_app()(new_scope, receive, send)
        return

    await _django_app(scope, receive, send)
