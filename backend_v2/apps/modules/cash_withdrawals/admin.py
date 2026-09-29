from django.contrib import admin, messages

from apps.modules.cash_withdrawals.models import (
    CashWithdrawalAlertRecipient,
    CashWithdrawalConfig,
    CashWithdrawalConfirmer,
    CashWithdrawalMessage,
    CashWithdrawalReceipt,
    CashWithdrawalRule,
)
from apps.modules.cash_withdrawals.services import close_receipt


class ConfirmerInline(admin.TabularInline):
    model = CashWithdrawalConfirmer
    extra = 0
    raw_id_fields = ("user",)


class AlertRecipientInline(admin.TabularInline):
    model = CashWithdrawalAlertRecipient
    extra = 0
    raw_id_fields = ("user",)


class RuleInline(admin.TabularInline):
    model = CashWithdrawalRule
    extra = 0
    raw_id_fields = ("wallet",)


@admin.register(CashWithdrawalConfig)
class CashWithdrawalConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "is_active", "card_telegram_chat", "alert_telegram_chat", "alert_after_days", "alert_hour")
    list_filter = ("is_active",)
    raw_id_fields = ("tenant", "card_telegram_chat", "alert_telegram_chat", "updated_by")
    inlines = [ConfirmerInline, AlertRecipientInline, RuleInline]


class MessageInline(admin.TabularInline):
    model = CashWithdrawalMessage
    extra = 0
    can_delete = False
    readonly_fields = ("kind", "telegram_message", "created_at")


@admin.register(CashWithdrawalReceipt)
class CashWithdrawalReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "request", "amount", "currency", "wallet", "status", "alert_count", "created_at")
    list_filter = ("status", "tenant")
    search_fields = ("request__id",)
    readonly_fields = (
        "tenant", "request", "wallet", "amount", "currency", "status", "confirmed_by", "confirmed_at",
        "cash_revenue", "closed_by", "closed_at", "last_alert_at", "alert_count", "created_at",
    )
    fields = readonly_fields + ("closed_comment",)
    inlines = [MessageInline]
    actions = ["close_without_revenue"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Закрыть без дохода (нужен заполненный комментарий)")
    def close_without_revenue(self, request, queryset):
        closed, skipped = 0, 0
        for receipt in queryset.filter(status=CashWithdrawalReceipt.Status.PENDING):
            if close_receipt(receipt_id=receipt.pk, actor=request.user, comment=receipt.closed_comment):
                closed += 1
            else:
                skipped += 1
        self.message_user(request, f"Закрыто: {closed}. Пропущено (нет комментария): {skipped}.", messages.INFO)
