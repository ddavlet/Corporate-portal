"""JWT pair for MCP OAuth — longer lifetime than portal defaults, scoped to MCP only."""

from __future__ import annotations

import os
from datetime import timedelta

from rest_framework_simplejwt.tokens import RefreshToken


def mcp_jwt_pair_for_user(user):
    """Return (refresh, access) with MCP-specific lifetimes (env-tunable)."""
    access_minutes = int(os.getenv("MCP_ACCESS_TOKEN_MINUTES", "60") or "60")
    refresh_days = int(os.getenv("MCP_REFRESH_TOKEN_DAYS", "7") or "7")

    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=timedelta(days=refresh_days))
    access = refresh.access_token
    access.set_exp(lifetime=timedelta(minutes=access_minutes))
    return refresh, access
