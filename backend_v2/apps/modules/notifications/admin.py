from django.contrib import admin

from apps.common.admin_labels import register_portal
from apps.modules.notifications.models import ActionItemPushState, PushSubscription


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PushSubscriptionAdmin(_ReadOnlyAdmin):
    # endpoint, p256dh and auth let anyone send pushes to the device: never shown in full.
    list_display = ("id", "user", "endpoint_masked", "created_at", "last_success_at", "revoked_at", "revoke_reason")
    list_filter = ("revoke_reason",)
    search_fields = ("user__username",)
    fields = (
        "user",
        "endpoint_masked",
        "user_agent",
        "created_at",
        "updated_at",
        "last_success_at",
        "synced_at",
        "sync_requested_at",
        "revoked_at",
        "revoke_reason",
    )
    readonly_fields = fields

    @admin.display(description="Endpoint")
    def endpoint_masked(self, obj):
        endpoint = obj.endpoint or ""
        scheme, sep, rest = endpoint.partition("://")
        host = rest.split("/", 1)[0] if sep else ""
        return f"{scheme}://{host}/…" if host else "…"


class ActionItemPushStateAdmin(_ReadOnlyAdmin):
    list_display = ("id", "tenant", "user", "tag", "sent_at", "closed_at")
    list_filter = ("tenant",)
    search_fields = ("tag", "user__username")
    readonly_fields = ("tenant", "user", "tag", "step_key", "sent_at", "closed_at")


register_portal(PushSubscription, "Push-подписка", "Push-подписки", PushSubscriptionAdmin)
register_portal(ActionItemPushState, "Push-уведомление о действии", "Push-уведомления о действиях", ActionItemPushStateAdmin)
