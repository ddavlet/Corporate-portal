"""JWT pair for MCP OAuth — bound to one tenant, longer lifetime than portal defaults."""

from __future__ import annotations

import os
from datetime import timedelta

from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.authentication import MCP_TENANT_CLAIM


def mcp_jwt_pair_for_user(user, tenant_id: int):
    """Return (refresh, access) carrying mcp_tenant_id, with MCP lifetimes (env-tunable)."""
    access_minutes = int(os.getenv("MCP_ACCESS_TOKEN_MINUTES", "60") or "60")
    refresh_days = int(os.getenv("MCP_REFRESH_TOKEN_DAYS", "7") or "7")

    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=timedelta(days=refresh_days))
    refresh[MCP_TENANT_CLAIM] = int(tenant_id)
    access = refresh.access_token
    access[MCP_TENANT_CLAIM] = int(tenant_id)
    access.set_exp(lifetime=timedelta(minutes=access_minutes))
    return refresh, access
