from django.contrib import admin

from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.wallets.resolution import get_or_create_corporate_wallet


@admin.register(CardExpense)
class CardExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "title", "amount", "currency", "expense_at", "created_at", "created_by")
    list_filter = ("tenant", "currency")
    search_fields = ("title", "note")

    def save_model(self, request, obj, form, change):
        if not obj.wallet_id:
            obj.wallet = get_or_create_corporate_wallet(tenant=obj.tenant, currency=obj.currency)
        super().save_model(request, obj, form, change)


@admin.register(CardRevenue)
class CardRevenueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "external_id",
        "revenue_date",
        "confirmed",
        "total_sum",
        "direction",
        "organization",
        "bank_expense_id",
        "created_at",
    )
    list_filter = ("tenant", "currency")
    search_fields = ("external_id", "title", "comment", "organization", "employee", "bank_expense_id")

    def save_model(self, request, obj, form, change):
        if not obj.wallet_id:
            obj.wallet = get_or_create_corporate_wallet(tenant=obj.tenant, currency=obj.currency)
        super().save_model(request, obj, form, change)

