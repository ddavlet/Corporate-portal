from django.conf import settings
from django.db import models


class OAuthClient(models.Model):
    """MCP OAuth 2.0 dynamically registered client (e.g. Claude Desktop, claude.ai)."""

    client_id = models.CharField(max_length=255, unique=True, db_index=True)
    client_name = models.CharField(max_length=255, blank=True)
    redirect_uris = models.JSONField(default=list)
    grant_types = models.JSONField(default=list)
    response_types = models.JSONField(default=list)
    scope = models.CharField(max_length=1000, blank=True)
    token_endpoint_auth_method = models.CharField(max_length=50, default="none")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_oauth_client"

    def __str__(self) -> str:
        return f"{self.client_name or self.client_id}"


class OAuthAuthorizationCode(models.Model):
    """Short-lived authorization code issued during the OAuth login flow."""

    code = models.CharField(max_length=255, unique=True, db_index=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_codes",
    )
    redirect_uri = models.TextField()
    redirect_uri_provided_explicitly = models.BooleanField(default=False)
    code_challenge = models.CharField(max_length=255)
    code_challenge_method = models.CharField(max_length=10, default="S256")
    scopes = models.JSONField(default=list)
    state = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_oauth_authorization_code"
        indexes = [
            models.Index(fields=["code", "used"], name="mcp_auth_code_idx"),
        ]

    def __str__(self) -> str:
        return f"code:{self.code[:12]}… user:{self.user_id}"
