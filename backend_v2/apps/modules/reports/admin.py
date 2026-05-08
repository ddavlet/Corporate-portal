from django.contrib import admin

from apps.modules.reports.models import TenantReportSettings


@admin.register(TenantReportSettings)
class TenantReportSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "pnl_source", "updated_at")
    raw_id_fields = ("tenant",)
    search_fields = ("tenant__subdomain",)
