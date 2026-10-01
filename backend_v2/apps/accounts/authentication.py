"""Portal JWT authentication: MCP connector tokens are never accepted here."""

from __future__ import annotations

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

# Set on every JWT issued for an MCP connector (apps/mcp_server/oauth/tokens.py,
# apps/mcp_server/http/service_key.py). Its presence marks a token as MCP-only.
MCP_TENANT_CLAIM = "mcp_tenant_id"


class RejectMcpTokenMixin:
    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)
        if token.get(MCP_TENANT_CLAIM) is not None:
            raise InvalidToken("MCP connector tokens are not accepted by the portal API")
        return token


class PortalJWTAuthentication(RejectMcpTokenMixin, JWTAuthentication):
    pass
