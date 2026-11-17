from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.corporate_card.models import CardExpense, CardExpenseAutoRequestConfig, CardRevenue


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


class CardExpenseAutoRequestConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "wallet", "is_enabled", "payment_purpose", "match_text", "updated_at")
    list_filter = ("tenant", "is_enabled")
    search_fields = ("id", "payment_purpose", "match_text")
    raw_id_fields = ("tenant", "wallet", "vendor_ref", "updated_by")


register_portal(CardExpense, "Корпоративная карта — расход", "Корпоративная карта — расходы", CardExpenseAdmin)
register_portal(CardRevenue, "Корпоративная карта — доход", "Корпоративная карта — доходы", CardRevenueAdmin)
register_portal(
    CardExpenseAutoRequestConfig,
    "Корпоративная карта — настройка автозаявок",
    "Корпоративная карта — настройки автозаявок",
    CardExpenseAutoRequestConfigAdmin,
)
