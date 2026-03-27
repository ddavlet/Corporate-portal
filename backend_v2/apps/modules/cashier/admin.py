from django.contrib import admin

from apps.modules.cashier.models import CashExpense, CashRevenue


@admin.register(CashExpense)
class CashExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "title",
        "amount",
        "currency",
        "expense_date",
        "category",
        "created_at",
        "created_by",
    )
    list_filter = ("tenant", "currency", "category")
    search_fields = ("title", "category", "note")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


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
        "created_by",
    )
    list_filter = ("tenant", "currency", "category", "payment_method", "status")
    search_fields = ("title", "category", "received_from", "reference_no", "note")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

