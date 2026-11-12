"""Portal token serializers."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import get_md5_hash_password

from apps.accounts.authentication import MCP_TENANT_CLAIM


class PortalTokenRefreshSerializer(TokenRefreshSerializer):
    """
    Refresh of a portal session (sliding: every refresh issues a new 30-day refresh token).

    Refused before a new pair is issued:
    - MCP connector refresh tokens: they keep their own lifetime (``MCP_REFRESH_TOKEN_DAYS``) and must not be
      renewed to the portal one;
    - tokens issued before the user's password changed (``CHECK_REVOKE_TOKEN``): a password change ends every
      session, otherwise a stolen refresh token could be renewed forever.
    """

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        if refresh.get(MCP_TENANT_CLAIM) is not None:
            raise InvalidToken("MCP connector tokens are not accepted by the portal API")
        if api_settings.CHECK_REVOKE_TOKEN:
            user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
            user = (
                get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first() if user_id else None
            )
            if user is not None and refresh.get(api_settings.REVOKE_TOKEN_CLAIM) != get_md5_hash_password(
                user.password
            ):
                raise InvalidToken("The user's password has been changed")
        return super().validate(attrs)
