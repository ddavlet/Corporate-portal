from django.contrib import admin

from apps.modules.bank_expenses.models import BankExpense, BankRevenue


@admin.register(BankExpense)
class BankExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "doc_date",
        "process_date",
        "doc_no",
        "account_name",
        "inn",
        "account_no",
        "mfo",
        "debit_turnover",
    )
    list_filter = ("tenant", "doc_date", "process_date", "mfo")
    search_fields = ("doc_no", "account_name", "inn", "account_no", "payment_purpose")


@admin.register(BankRevenue)
class BankRevenueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant_subdomain",
        "doc_date",
        "process_date",
        "doc_no",
        "account_name",
        "inn",
        "account_no",
        "mfo",
        "kredit_turnover",
    )
    list_filter = ("tenant_subdomain", "doc_date", "process_date", "mfo")
    search_fields = ("doc_no", "account_name", "inn", "account_no", "payment_purpose")

