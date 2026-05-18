"""MCP tools for tenant integration configuration.

Sensitive encrypted fields (tokens, secrets) are intentionally excluded
from responses — only non-secret metadata is returned.
Only admin users can access these tools.
"""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_admin_access


def get_integration_config(token: str, tenant_id: int) -> dict[str, Any]:
    """Return the integration configuration for a tenant (admin only).

    Encrypted secrets are never included. Returns Telegram OIDC metadata,
    messaging gateway settings, and whether each token is configured.
    """
    _, tenant = require_admin_access(token, tenant_id)

    from apps.tenants.models import TenantIntegrationConfig

    try:
        cfg = TenantIntegrationConfig.objects.get(tenant=tenant)
    except TenantIntegrationConfig.DoesNotExist:
        return {"tenant_id": tenant_id, "configured": False}

    return {
        "tenant_id": tenant_id,
        "configured": True,
        "updated_at": cfg.updated_at.isoformat(),
        "updated_by_id": cfg.updated_by_id,
        # Indicate presence only — never expose the secret value
        "n8n_integration_token_set": bool(cfg.n8n_integration_token_enc),
        "requests_file_gateway_token_set": bool(cfg.requests_file_gateway_token_enc),
        "telegram_oidc_client_id": cfg.telegram_oidc_client_id,
        "telegram_oidc_client_secret_set": bool(cfg.telegram_oidc_client_secret_enc),
        "telegram_oidc_redirect_uri": cfg.telegram_oidc_redirect_uri,
        "messaging_gateway_feedback_recipient_id": cfg.messaging_gateway_feedback_recipient_id,
        "messaging_gateway_feedback_action": cfg.messaging_gateway_feedback_action,
    }
