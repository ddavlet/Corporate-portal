# backend_v2/apps/mcp_server/http/service_key.py
"""
ASGI middleware: resolve an X-Service-Key header into a Bearer JWT before
FastMCP's own OAuth token verifier sees the request.

No X-Service-Key header -> pass through unchanged (normal Authorization path,
either a manually-set human JWT or one obtained through /oauth/login).
Invalid/inactive key -> 401 immediately; the wrapped app is never called
(fail-closed — no silent fallback to Authorization).
"""

from __future__ import annotations

import json

from asgiref.sync import sync_to_async

_HEADER = b"x-service-key"


async def _reject(send, message: str) -> None:
    body = json.dumps({"error": message}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _mint_service_access_token(service_user) -> str:
    """Mint a short-lived AccessToken for a service_user, tagged svc=True.

    Access-token only (no RefreshToken/OutstandingToken row) — safe to call
    on every request without growing the simplejwt blacklist table.
    """
    from rest_framework_simplejwt.tokens import AccessToken

    token = AccessToken.for_user(service_user)
    token["svc"] = True
    return str(token)


def with_service_key_auth(app):
    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_key = headers.get(_HEADER)
        if raw_key is None:
            await app(scope, receive, send)
            return

        from apps.mcp_server.services import verify_service_key

        credential = await sync_to_async(verify_service_key, thread_sensitive=True)(
            raw_key.decode("latin-1")
        )
        if credential is None:
            await _reject(send, "Invalid or inactive service key")
            return

        service_user = await sync_to_async(lambda: credential.service_user, thread_sensitive=True)()
        token = _mint_service_access_token(service_user)

        from apps.mcp_server.models import McpServiceCredential
        from django.utils import timezone

        await McpServiceCredential.objects.filter(pk=credential.pk).aupdate(
            last_used_at=timezone.now()
        )

        new_headers = [(k, v) for k, v in scope.get("headers", []) if k != b"authorization"]
        new_headers.append((b"authorization", f"Bearer {token}".encode("latin-1")))

        await app({**scope, "headers": new_headers}, receive, send)

    return middleware
