"""
KolbergOAuthProvider — реализация OAuthAuthorizationServerProvider для FastMCP.

Поток авторизации:
  1. MCP SDK вызывает authorize() → редирект на https://<tenant>/mcp/login/?t=<signed_params>
  2. Пользователь логинится через OTP (Django-вью)
  3. После логина Django создаёт OAuthAuthorizationCode и редиректит на redirect_uri?code=...
  4. FastMCP вызывает exchange_authorization_code() → simplejwt access+refresh токены
  5. load_access_token() валидирует JWT и устанавливает contextvar для tools
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta

from django.core import signing

from mcp.server.auth.provider import (
    OAuthAuthorizationServerProvider,
    AuthorizationParams,
    AuthorizationCode,
    RefreshToken,
    AccessToken,
    AuthorizeError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from apps.mcp_server.auth import set_request_token, _decode_token

_SIGN_SALT = "mcp-oauth-authorize"
_CODE_TTL_SECONDS = 600  # 10 minutes


class KolbergAuthCode(AuthorizationCode):
    user_id: int
    tenant_id: int | None = None


class KolbergRefreshToken(RefreshToken):
    user_id: int
    tenant_id: int | None = None


class KolbergAccessToken(AccessToken):
    user_id: int


class KolbergOAuthProvider(
    OAuthAuthorizationServerProvider[KolbergAuthCode, KolbergRefreshToken, KolbergAccessToken]
):
    # ------------------------------------------------------------------
    # Client registry
    # ------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        from apps.mcp_server.oauth.models import OAuthClient

        try:
            client = await OAuthClient.objects.aget(client_id=client_id)
        except OAuthClient.DoesNotExist:
            return None
        return self._to_full(client)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        from apps.mcp_server.oauth.models import OAuthClient

        await OAuthClient.objects.aupdate_or_create(
            client_id=client_info.client_id,
            defaults={
                "client_name": client_info.client_name or "",
                "redirect_uris": [str(u) for u in (client_info.redirect_uris or [])],
                "grant_types": list(client_info.grant_types or []),
                "response_types": list(client_info.response_types or []),
                "scope": client_info.scope or "",
                "token_endpoint_auth_method": client_info.token_endpoint_auth_method or "none",
            },
        )

    # ------------------------------------------------------------------
    # Authorization flow
    # ------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Redirect user to the tenant's OTP login page with signed OAuth params."""
        from apps.mcp_server.tenant_context import current_tenant

        tenant = current_tenant()
        if params.resource and params.resource.rstrip("/") != tenant.base_url:
            raise AuthorizeError(
                error="invalid_request",
                error_description="resource does not match this MCP server",
            )
        payload = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "state": params.state or "",
            "scopes": params.scopes or [],
            "tenant_id": tenant.id,
        }
        signed = signing.dumps(payload, salt=_SIGN_SALT, compress=True)
        return f"{tenant.base_url}/login/?t={signed}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> KolbergAuthCode | None:
        from apps.mcp_server.oauth.models import OAuthAuthorizationCode

        try:
            record = await OAuthAuthorizationCode.objects.select_related("client").aget(
                code=authorization_code,
                client__client_id=client.client_id,
                used=False,
            )
        except OAuthAuthorizationCode.DoesNotExist:
            return None

        if record.expires_at < datetime.now(tz=timezone.utc):
            return None

        from apps.mcp_server.tenant_context import current_tenant

        if record.tenant_id != current_tenant().id:
            return None

        return KolbergAuthCode(
            code=record.code,
            client_id=client.client_id,
            scopes=record.scopes,
            expires_at=record.expires_at.timestamp(),
            code_challenge=record.code_challenge,
            redirect_uri=record.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=record.redirect_uri_provided_explicitly,
            user_id=record.user_id,
            tenant_id=record.tenant_id,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: KolbergAuthCode
    ) -> OAuthToken:
        from apps.mcp_server.oauth.models import OAuthAuthorizationCode
        from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user
        from apps.accounts.models import User

        await OAuthAuthorizationCode.objects.filter(code=authorization_code.code).aupdate(used=True)

        user = await User.objects.aget(id=authorization_code.user_id)
        refresh, access = mcp_jwt_pair_for_user(user, authorization_code.tenant_id)

        return OAuthToken(
            access_token=str(access),
            token_type="bearer",
            expires_in=int(access.lifetime.total_seconds()),
            refresh_token=str(refresh),
            scope=" ".join(authorization_code.scopes) or "mcp",
        )

    # ------------------------------------------------------------------
    # Refresh token
    # ------------------------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> KolbergRefreshToken | None:
        from rest_framework_simplejwt.tokens import RefreshToken as JwtRefresh
        from rest_framework_simplejwt.exceptions import TokenError as JwtTokenError

        from apps.accounts.authentication import MCP_TENANT_CLAIM
        from apps.mcp_server.tenant_context import current_tenant

        try:
            token = JwtRefresh(refresh_token)
            token_tenant = token.get(MCP_TENANT_CLAIM)
            if token_tenant is None or int(token_tenant) != current_tenant().id:
                return None
            return KolbergRefreshToken(
                token=refresh_token,
                client_id=client.client_id,
                scopes=["mcp"],
                user_id=int(token["user_id"]),
                tenant_id=int(token_tenant),
            )
        except (JwtTokenError, KeyError, ValueError):
            return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: KolbergRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        from rest_framework_simplejwt.tokens import RefreshToken as JwtRefresh
        from rest_framework_simplejwt.exceptions import TokenError as JwtTokenError

        try:
            old_refresh = JwtRefresh(refresh_token.token)
            old_refresh.blacklist()  # revoke old token (requires simplejwt blacklist app)
        except Exception:
            pass

        from apps.accounts.models import User

        try:
            user = await User.objects.aget(id=refresh_token.user_id)
        except User.DoesNotExist:
            raise TokenError(error="invalid_grant", error_description="User not found")

        from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user

        new_refresh, access = mcp_jwt_pair_for_user(user, refresh_token.tenant_id)

        return OAuthToken(
            access_token=str(access),
            token_type="bearer",
            expires_in=int(access.lifetime.total_seconds()),
            refresh_token=str(new_refresh),
            scope=" ".join(scopes) or "mcp",
        )

    # ------------------------------------------------------------------
    # Access token validation (called per-request by FastMCP middleware)
    # ------------------------------------------------------------------

    async def load_access_token(self, token: str) -> KolbergAccessToken | None:
        try:
            user_id = _decode_token(token)
        except PermissionError:
            return None

        # Make the token available to MCP tools via contextvar (same async task).
        set_request_token(token)

        return KolbergAccessToken(
            token=token,
            client_id="kolberg",
            scopes=["mcp"],
            user_id=user_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_full(client) -> OAuthClientInformationFull:
        return OAuthClientInformationFull(
            client_id=client.client_id,
            client_name=client.client_name or None,
            redirect_uris=client.redirect_uris,
            grant_types=client.grant_types or ["authorization_code"],
            response_types=client.response_types or ["code"],
            scope=client.scope or None,
            token_endpoint_auth_method=client.token_endpoint_auth_method,
        )


def create_authorization_code(
    *,
    client_id: str,
    user_id: int,
    tenant_id: int,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    code_challenge: str,
    code_challenge_method: str,
    scopes: list[str],
    state: str,
) -> str:
    """Create and persist an authorization code. Returns the code string."""
    from apps.mcp_server.oauth.models import OAuthClient, OAuthAuthorizationCode

    client = OAuthClient.objects.get(client_id=client_id)
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=_CODE_TTL_SECONDS)

    OAuthAuthorizationCode.objects.create(
        code=code,
        client=client,
        user_id=user_id,
        tenant_id=tenant_id,
        redirect_uri=redirect_uri,
        redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scopes=scopes,
        state=state,
        expires_at=expires_at,
    )
    return code
