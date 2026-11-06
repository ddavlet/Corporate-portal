from django.contrib import admin

from apps.modules.cash_desk.models import CashDeskConfig, CashDeskMessage, CashRegisterTransferTarget


@admin.register(CashDeskConfig)
class CashDeskConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "is_active", "telegram_chat", "updated_at")
    list_filter = ("is_active",)
    raw_id_fields = ("tenant", "telegram_chat", "updated_by")


@admin.register(CashRegisterTransferTarget)
class CashRegisterTransferTargetAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "request", "to_wallet", "to_amount", "created_at")
    list_filter = ("tenant",)
    raw_id_fields = ("tenant", "request", "to_wallet")


@admin.register(CashDeskMessage)
class CashDeskMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "request", "kind", "status", "error", "revenue_error", "created_at")
    list_filter = ("status", "kind", "tenant")
    search_fields = ("request__id",)
    readonly_fields = (
        "tenant", "request", "kind", "status", "telegram_message", "error", "revenue_error", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
