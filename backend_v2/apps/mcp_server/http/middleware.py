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
        header_value = f'Bearer resource_metadata="{protected_resource_metadata_url()}"'.encode("ascii")

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                headers = list(message.get("headers", []))
                replaced = False
                for i, (name, value) in enumerate(headers):
                    if name.lower() == header_name:
                        existing = value.decode("latin-1")
                        if "resource_metadata=" not in existing:
                            headers[i] = (
                                name,
                                f'{existing}, resource_metadata="{protected_resource_metadata_url()}"'.encode(
                                    "latin-1"
                                ),
                            )
                        replaced = True
                        break
                if not replaced:
                    headers.append((header_name, header_value))
                message = {**message, "headers": headers}
            await send(message)

        await app(scope, receive, send_wrapper)

    return middleware
