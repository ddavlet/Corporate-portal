from django.contrib import admin

from apps.modules.telegram_approvals.models import TelegramMessage, TelegramMessageHistory, TenantTelegramChat


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
