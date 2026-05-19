"""
Serve McpLoginView directly from ASGI (bypasses Django URLconf).

Production must not depend on urls.py registering /oauth-login/ — Traefik + ASGI
routing is enough; the view is invoked here.
"""

from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from apps.mcp_server.oauth.views import McpLoginView

_view = McpLoginView.as_view()
_factory = RequestFactory()


def _build_http_request(scope: dict, body: bytes) -> HttpRequest:
    from urllib.parse import parse_qs

    method = scope.get("method", "GET").upper()
    path = scope.get("path", "/")
    query_string = scope.get("query_string", b"").decode("latin-1")

    headers = {}
    for key, val in scope.get("headers", []):
        headers[key.decode("latin-1").lower()] = val.decode("latin-1")

    extra = {}
    if host := headers.get("host"):
        extra["HTTP_HOST"] = host

    if method == "GET":
        data = {k: v[0] for k, v in parse_qs(query_string).items()}
        return _factory.get(path, data=data, **extra)

    content_type = headers.get("content-type", "application/x-www-form-urlencoded")
    if content_type.startswith("application/x-www-form-urlencoded"):
        data = {k: v[0] for k, v in parse_qs(body.decode("latin-1")).items()}
        return _factory.post(path, data=data, content_type=content_type, **extra)
    return _factory.post(path, data=body, content_type=content_type, **extra)


async def _http_response_to_asgi(response: HttpResponse, send) -> None:
    body = response.content or b""
    headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in response.items()]
    for cookie in response.cookies.values():
        headers.append((b"set-cookie", cookie.output(header="").encode("latin-1")))

    await send(
        {
            "type": "http.response.start",
            "status": response.status_code,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


def _is_legacy_login_path(path: str) -> bool:
    p = (path or "/").rstrip("/") or "/"
    return p in ("/mcp/login", "/oauth/mcp/login")


async def _redirect_legacy_login(scope: dict, send) -> None:
    from apps.mcp_server.oauth.metadata import mcp_oauth_login_url

    target = mcp_oauth_login_url().rstrip("/") + "/"
    qs = scope.get("query_string", b"").decode("latin-1")
    if qs:
        target = f"{target}?{qs}"
    headers = [(b"location", target.encode("latin-1"))]
    await send({"type": "http.response.start", "status": 301, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


async def serve_mcp_login(scope: dict, receive, send) -> None:
    path = scope.get("path", "")
    if _is_legacy_login_path(path):
        await _redirect_legacy_login(scope, send)
        return

    body = b""
    if scope.get("method", "GET").upper() == "POST":
        chunks = []
        while True:
            message = await receive()
            if message["type"] == "http.request":
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    break
            elif message["type"] == "http.disconnect":
                return
        body = b"".join(chunks)

    request = _build_http_request(scope, body)
    response = await sync_to_async(_view, thread_sensitive=True)(request)
    await _http_response_to_asgi(response, send)
