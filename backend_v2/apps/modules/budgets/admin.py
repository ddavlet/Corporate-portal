from django.contrib import admin

from apps.modules.budgets.models import Budget


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "category", "period_type", "limit_amount", "currency", "is_active", "created_at")
    list_filter = ("tenant", "period_type", "currency", "is_active")
    search_fields = ("name",)
