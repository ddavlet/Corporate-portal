from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.reports.models import TenantReportSettings


class TenantReportSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "pnl_source", "cashflow_source", "updated_at")
    list_filter = ("pnl_source", "cashflow_source")
    autocomplete_fields = ("tenant",)


register_portal(TenantReportSettings, "Настройки отчётов", "Настройки отчётов", TenantReportSettingsAdmin)
