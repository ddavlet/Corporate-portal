from django.contrib import admin

from apps.modules.bank_expenses.models import BankExpense, BankRevenue


@admin.register(BankExpense)
class BankExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "created_at",
        "created_by",
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

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(BankRevenue)
class BankRevenueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant_subdomain",
        "created_at",
        "created_by",
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

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

