"""
Register sync Django ORM callables as FastMCP tools safe under ASGI (HTTP OAuth).

FastMCP Streamable HTTP invokes tools in an async context; bare ORM raises
SynchronousOnlyOperation. thread_sensitive=True keeps request contextvars (JWT).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from asgiref.sync import sync_to_async

F = TypeVar("F", bound=Callable)


def django_mcp_tool(mcp) -> Callable[[F], F]:
    """Like ``@mcp.tool()`` but runs the handler via ``sync_to_async``."""

    def decorator(fn: F) -> F:
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            return await sync_to_async(fn, thread_sensitive=True)(*args, **kwargs)

        async_wrapper.__annotations__ = getattr(fn, "__annotations__", {})
        mcp.tool()(async_wrapper)
        return fn

    return decorator
