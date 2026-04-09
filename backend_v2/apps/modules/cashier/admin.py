from django.contrib import admin

from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.wallets.resolution import get_or_create_cash_wallet


@admin.register(CashExpense)
class CashExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "external_id",
        "tenant",
        "title",
        "amount",
        "currency",
        "expense_at",
        "expense_year",
        "expense_month",
        "expense_day",
        "created_at",
        "created_by",
    )
    list_filter = ("tenant", "currency", "expense_year", "expense_month")
    search_fields = ("external_id", "title", "note")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        if not obj.wallet_id:
            obj.wallet = get_or_create_cash_wallet(tenant=obj.tenant, currency=obj.currency)
        super().save_model(request, obj, form, change)


@admin.register(CashRevenue)
class CashRevenueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "external_id",
        "revenue_at",
        "operation",
        "counterparty",
        "total_sum",
        "confirmed",
        "created_at",
        "created_by",
    )
    list_filter = ("tenant", "confirmed")
    search_fields = ("external_id", "operation", "counterparty", "comment")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        if not obj.wallet_id:
            obj.wallet = get_or_create_cash_wallet(tenant=obj.tenant, currency="UZS")
        super().save_model(request, obj, form, change)

