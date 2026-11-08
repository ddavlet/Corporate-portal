from django.contrib import admin

from apps.modules.dividend_payouts.models import DividendPayoutLink, DividendPayoutRule


@admin.register(DividendPayoutRule)
class DividendPayoutRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "payment_purpose", "return_type", "recipient", "is_active", "updated_at")
    list_filter = ("is_active", "return_type", "recipient", "tenant")
    search_fields = ("payment_purpose",)
    raw_id_fields = ("tenant",)


@admin.register(DividendPayoutLink)
class DividendPayoutLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "invest_return", "rule", "status", "error", "created_at")
    list_filter = ("status",)
    search_fields = ("request__id",)
    readonly_fields = ("request", "invest_return", "rule", "status", "error", "created_at")
    actions = ("retry_failed",)

    @admin.action(description="Повторить создание выплаты (только для ошибок)")
    def retry_failed(self, request, queryset):
        from apps.modules.dividend_payouts.services import retry_failed_link

        created = failed = 0
        for link in queryset.filter(status=DividendPayoutLink.Status.FAILED):
            link = retry_failed_link(link)
            if link.status == DividendPayoutLink.Status.CREATED:
                created += 1
            else:
                failed += 1
        self.message_user(request, f"Создано выплат: {created}; снова ошибка: {failed}.")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
