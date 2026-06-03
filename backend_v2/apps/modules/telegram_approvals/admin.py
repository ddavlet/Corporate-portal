from django.contrib import admin

from apps.modules.telegram_approvals.models import TelegramMessage, TenantTelegramChat


@admin.register(TelegramMessage)
class TelegramMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "recipient_id", "message_id", "sent_at")
    list_filter = ("tenant",)
    readonly_fields = ("sent_at",)
    raw_id_fields = ("tenant",)


@admin.register(TenantTelegramChat)
class TenantTelegramChatAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "chat_id", "is_active")
    list_filter = ("tenant", "is_active")
