"""MCP-клиент агента: короткий токен спросившего пользователя и сессия к MCP портала.

MCP вызывается по внутренней сети Docker (config.MCP_INTERNAL_URL); тенант MCP
определяет по Host, поэтому Host — поддомен тенанта. Токен — только access
(как в apps/mcp_server/http/service_key.py), без записи refresh-токена.
"""

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import AsyncIterator, Protocol

from django.conf import settings

from .config import MCP_INTERNAL_URL, MCP_TOKEN_MINUTES

logger = logging.getLogger(__name__)

# connect/write/pool и чтение (MCP-инструмент может считать отчёт долго).
_HTTP_TIMEOUT_SECONDS = 30.0
_HTTP_READ_TIMEOUT_SECONDS = 300.0
# Защита от бесконечной пагинации tools/list.
_LIST_TOOLS_PAGE_CAP = 50


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    read_only: bool


def tool_spec_from_mcp(tool) -> ToolSpec:
    """mcp.types.Tool → ToolSpec. Без пометки read_only_hint=True инструмент считается изменяющим."""
    annotations = getattr(tool, "annotations", None)
    read_only = annotations is not None and annotations.read_only_hint is True
    return ToolSpec(
        name=tool.name,
        description=tool.description or "",
        input_schema=dict(tool.input_schema or {"type": "object"}),
        read_only=read_only,
    )


def mint_mcp_access_token(user, tenant_id: int) -> str:
    """Короткий access-токен пользователя для MCP тенанта (claim mcp_tenant_id), без refresh."""
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.authentication import MCP_TENANT_CLAIM

    token = AccessToken.for_user(user)
    token[MCP_TENANT_CLAIM] = int(tenant_id)
    token.set_exp(lifetime=timedelta(minutes=MCP_TOKEN_MINUTES))
    return str(token)


class McpSession(Protocol):
    """То, чем пользуется цикл агента (реальная сессия и фейк в тестах)."""

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]: ...


def _result_text(result) -> str:
    parts = [block.text for block in (result.content or []) if getattr(block, "type", None) == "text"]
    if parts:
        return "\n".join(parts)
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, default=str)
    return ""


class ClientMcpSession:
    """McpSession поверх mcp.Client (streamable HTTP)."""

    def __init__(self, client) -> None:
        self._client = client

    async def list_tools(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        cursor = None
        for _ in range(_LIST_TOOLS_PAGE_CAP):
            page = await self._client.list_tools(cursor=cursor)
            specs.extend(tool_spec_from_mcp(tool) for tool in page.tools)
            cursor = page.next_cursor
            if not cursor:
                break
        else:
            logger.warning("ai_assistant MCP: tools/list pagination cap reached (%s pages)", _LIST_TOOLS_PAGE_CAP)
        return specs

    async def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        try:
            result = await self._client.call_tool(name, arguments or {})
        except Exception as exc:
            logger.exception("ai_assistant MCP: tool call failed: tool=%s", name)
            return f"Tool error: {exc}", True
        return _result_text(result), bool(result.is_error)


@asynccontextmanager
async def open_mcp(*, tenant_subdomain: str, token: str) -> AsyncIterator[McpSession]:
    """Сессия к MCP портала от имени владельца токена, на хосте <subdomain>.<BASE_DOMAIN>."""
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").lstrip(".")
    headers = {
        "Authorization": f"Bearer {token}",
        "Host": f"{tenant_subdomain}.{base_domain}",
    }
    http_client = httpx2.AsyncClient(
        headers=headers,
        timeout=httpx2.Timeout(_HTTP_TIMEOUT_SECONDS, read=_HTTP_READ_TIMEOUT_SECONDS),
    )
    async with http_client:
        transport = streamable_http_client(MCP_INTERNAL_URL, http_client=http_client)
        async with Client(transport) as client:
            yield ClientMcpSession(client)
