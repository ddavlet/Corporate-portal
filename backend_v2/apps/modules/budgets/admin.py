from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.budgets.models import Budget


class BudgetAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "category", "period_type", "limit_amount", "currency", "is_active")
    list_filter = ("tenant", "period_type", "is_active", "currency")
    search_fields = ("name",)
    raw_id_fields = ("tenant", "category", "created_by")


register_portal(Budget, "Бюджет", "Бюджеты", BudgetAdmin)
