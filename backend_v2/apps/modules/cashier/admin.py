from django.contrib import admin

from apps.modules.cashier.models import CashExpense, CashRevenue


@admin.register(CashExpense)
class CashExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "title", "amount", "currency", "expense_date", "category", "created_at")
    list_filter = ("tenant", "currency", "category")
    search_fields = ("title", "category", "note")


@admin.register(CashRevenue)
class CashRevenueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "title",
        "amount",
        "currency",
        "revenue_date",
        "category",
        "received_from",
        "payment_method",
        "reference_no",
        "status",
        "created_at",
    )
    list_filter = ("tenant", "currency", "category", "payment_method", "status")
    search_fields = ("title", "category", "received_from", "reference_no", "note")

