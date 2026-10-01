"""
Register sync Django ORM callables as MCP tools bound to the request's tenant.

- Runs the handler via sync_to_async (thread_sensitive=True keeps request
  contextvars: JWT and tenant) — bare ORM raises SynchronousOnlyOperation in ASGI.
- A `tenant_id` parameter is removed from the tool schema and filled from the
  tenant resolved from the Host subdomain (apps.mcp_server.tenant_context).
- The tool's Access rule is recorded in TOOL_ACCESS for list_tools filtering.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from asgiref.sync import sync_to_async

from apps.mcp_server.access import Access

F = TypeVar("F", bound=Callable)

TOOL_ACCESS: dict[str, Access] = {}


def django_mcp_tool(mcp) -> Callable[..., Callable[[F], F]]:
    def tool(*, access: Access) -> Callable[[F], F]:
        def decorator(fn: F) -> F:
            sig = inspect.signature(fn)
            takes_tenant = "tenant_id" in sig.parameters
            public_params = [p for p in sig.parameters.values() if p.name != "tenant_id"]

            @wraps(fn)
            async def async_wrapper(**kwargs):
                if takes_tenant:
                    from apps.mcp_server.tenant_context import current_tenant

                    kwargs["tenant_id"] = current_tenant().id
                return await sync_to_async(fn, thread_sensitive=True)(**kwargs)

            async_wrapper.__signature__ = sig.replace(parameters=public_params)
            async_wrapper.__annotations__ = {
                k: v for k, v in getattr(fn, "__annotations__", {}).items() if k != "tenant_id"
            }
            mcp.tool()(async_wrapper)
            TOOL_ACCESS[fn.__name__] = access
            return fn

        return decorator

    return tool
