from django.contrib import admin

from apps.modules.telegram_approvals.models import (
    TelegramChatRegistry,
    TelegramEvent,
    TelegramMessage,
    TelegramMessageHistory,
    TenantTelegramChat,
)


class TelegramMessageHistoryInline(admin.TabularInline):
    model = TelegramMessageHistory
    extra = 0
    readonly_fields = ("action", "message_id", "recipient_id", "success", "error_message", "actor_user", "actor_external_user_id", "created_at")
    fields = ("created_at", "action", "message_id", "success", "error_message", "actor_user", "actor_external_user_id")
    ordering = ("created_at",)
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TelegramMessage)
class TelegramMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "recipient_id", "message_id", "sent_at", "resend_count")
    list_filter = ("tenant",)
    readonly_fields = ("sent_at", "resend_count", "last_resend_at")
    raw_id_fields = ("tenant",)
    inlines = [TelegramMessageHistoryInline]


@admin.register(TelegramMessageHistory)
class TelegramMessageHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "telegram_message", "action", "message_id", "success", "actor_user", "created_at")
    list_filter = ("action", "success")
    readonly_fields = tuple(f.name for f in TelegramMessageHistory._meta.get_fields() if hasattr(f, "name"))
    raw_id_fields = ("telegram_message", "actor_user")


@admin.register(TenantTelegramChat)
class TenantTelegramChatAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "chat_id", "is_active")
    list_filter = ("tenant", "is_active")


@admin.register(TelegramChatRegistry)
class TelegramChatRegistryAdmin(admin.ModelAdmin):
    list_display = ("chat_id", "chat_type", "name", "username", "first_seen_at", "last_seen_at")
    search_fields = ("chat_id", "name", "username")
    list_filter = ("chat_type",)
    readonly_fields = ("first_seen_at", "last_seen_at")


@admin.register(TelegramEvent)
class TelegramEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "direction", "chat_id", "sender_id", "message_id_tg", "timestamp")
    list_filter = ("event_type", "direction")
    search_fields = ("chat_id", "message_text", "sender_id")
    readonly_fields = ("chat_registry", "chat_id", "event_type", "direction", "timestamp", "payload",
                       "update_id", "sender_id", "message_id_tg", "message_text")
    date_hierarchy = "timestamp"
    raw_id_fields = ("chat_registry",)
