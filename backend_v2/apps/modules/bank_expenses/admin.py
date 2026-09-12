from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.bank_expenses.models import BankExpense, BankRevenue


class BankExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "doc_date", "doc_no", "debit_turnover", "vendor", "wallet")
    list_filter = ("tenant",)
    search_fields = ("id", "doc_no", "payment_purpose", "external_id")
    raw_id_fields = ("tenant", "created_by", "vendor", "wallet")
    date_hierarchy = "doc_date"


class BankRevenueAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "doc_date", "doc_no", "kredit_turnover", "account_name", "wallet")
    list_filter = ("tenant",)
    search_fields = ("id", "doc_no", "payment_purpose", "account_name", "inn", "external_id")
    raw_id_fields = ("tenant", "created_by", "wallet")
    date_hierarchy = "doc_date"


register_portal(BankExpense, "Банк — расход", "Банк — расходы", BankExpenseAdmin)
register_portal(BankRevenue, "Банк — доход", "Банк — доходы", BankRevenueAdmin)
