from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.cashier.models import CashExpense, CashRevenue


class CashExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "title", "amount", "currency", "expense_at", "confirmed", "wallet")
    list_filter = ("tenant", "confirmed", "currency")
    search_fields = ("id", "title", "external_id", "note")
    raw_id_fields = ("tenant", "created_by", "vendor", "wallet")
    date_hierarchy = "expense_at"


class CashRevenueAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "operation", "total_sum", "currency", "revenue_at", "confirmed", "wallet")
    list_filter = ("tenant", "confirmed", "currency")
    search_fields = ("id", "operation", "counterparty", "external_id", "comment")
    raw_id_fields = ("tenant", "created_by", "wallet")


register_portal(CashExpense, "Касса — расход", "Касса — расходы", CashExpenseAdmin)
register_portal(CashRevenue, "Касса — доход", "Касса — доходы", CashRevenueAdmin)
