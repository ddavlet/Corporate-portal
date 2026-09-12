from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.corporate_card.models import CardExpense, CardRevenue


class CardExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "title", "amount", "currency", "expense_at", "wallet")
    list_filter = ("tenant", "currency")
    search_fields = ("id", "title", "external_id", "note")
    raw_id_fields = ("tenant", "created_by", "wallet")
    date_hierarchy = "expense_at"


class CardRevenueAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "operation", "total_sum", "currency", "revenue_at", "confirmed", "wallet")
    list_filter = ("tenant", "confirmed", "currency")
    search_fields = ("id", "operation", "counterparty", "external_id", "comment")
    raw_id_fields = ("tenant", "created_by", "wallet")
    date_hierarchy = "revenue_at"


register_portal(CardExpense, "Корпоративная карта — расход", "Корпоративная карта — расходы", CardExpenseAdmin)
register_portal(CardRevenue, "Корпоративная карта — доход", "Корпоративная карта — доходы", CardRevenueAdmin)
