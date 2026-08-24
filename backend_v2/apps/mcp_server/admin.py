# backend_v2/apps/mcp_server/admin.py
from django.contrib import admin, messages

from apps.mcp_server.models import McpServiceCredential
from apps.mcp_server.services import provision_service_credential, sync_tenant_access


@admin.register(McpServiceCredential)
class McpServiceCredentialAdmin(admin.ModelAdmin):
    list_display = ("name", "key_prefix", "is_active", "created_at", "last_used_at")
    filter_horizontal = ("tenants",)
    fields = ("name", "tenants", "is_active", "key_prefix", "service_user", "created_at", "last_used_at")
    readonly_fields = ("key_prefix", "service_user", "created_at", "last_used_at")

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return

        tenant_ids = [t.id for t in form.cleaned_data.get("tenants", [])]
        credential, raw_key = provision_service_credential(name=obj.name, tenant_ids=tenant_ids)
        credential.is_active = obj.is_active
        credential.save(update_fields=["is_active"])

        # Point the admin form's in-memory instance at the row provision_service_credential
        # already created, so Django's own post-save machinery (save_related below,
        # the redirect to the change page) operates on the real, persisted object.
        obj.pk = credential.pk
        obj.key_prefix = credential.key_prefix
        obj.key_hash = credential.key_hash
        obj.service_user_id = credential.service_user_id
        obj.created_at = credential.created_at

        self.message_user(
            request,
            f"Service key (shown once, save it now): {raw_key}",
            level=messages.WARNING,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sync_tenant_access(form.instance)
