from __future__ import annotations

from django.conf import settings
from django.db import models


class McpServiceCredential(models.Model):
    """A long-lived, tenant-scoped API key for non-human MCP callers.

    Resolves to a real `service_user` with an active TenantMembership and an
    admin TenantUserRole in every one of `tenants` (see
    apps/mcp_server/services.py::sync_tenant_access). That is what lets every
    existing tool and every require_module_access/require_admin_access check
    work for a service caller with zero changes to tools/*.py — the service
    caller genuinely is a tenant admin, just not a human.
    """

    key_prefix = models.CharField(max_length=16, unique=True, db_index=True)
    key_hash = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    service_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_service_credential",
    )
    tenants = models.ManyToManyField(
        "tenants.Tenant", related_name="mcp_service_credentials", blank=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_service_credential"

    def __str__(self) -> str:
        return f"{self.name} ({self.key_prefix})"
