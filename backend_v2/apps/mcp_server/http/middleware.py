"""
ASGI middleware: add MCP resource_metadata hint to 401 responses (RFC 9728).
"""

from __future__ import annotations

from apps.mcp_server.oauth.metadata import protected_resource_metadata_url


def with_mcp_resource_metadata(app):
    """Wrap an ASGI app so 401 responses include resource_metadata for OAuth discovery."""

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        header_name = b"www-authenticate"
        canonical_meta = protected_resource_metadata_url()

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                headers = [(n, v) for n, v in message.get("headers", []) if n.lower() != header_name]
                # Always use Django-served metadata URL (FastMCP may append a wrong /mcp suffix).
                headers.append(
                    (
                        header_name,
                        f'Bearer error="invalid_token", error_description="Authentication required", '
                        f'resource_metadata="{canonical_meta}"'.encode("latin-1"),
                    )
                )
                message = {**message, "headers": headers}
            await send(message)

        await app(scope, receive, send_wrapper)

    return middleware
