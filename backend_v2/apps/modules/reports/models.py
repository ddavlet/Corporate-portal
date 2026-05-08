from django.db import models

from apps.tenants.models import Tenant


class TenantReportSettings(models.Model):
    """
    Per-tenant configuration for reports (PnL filters, period, etc.).
    Required for backend PnL when PNL_REPORT_SOURCE=backend — no code fallbacks if missing.
    """

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="report_settings",
    )
    pnl_config = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenant_report_settings"

    def __str__(self) -> str:
        return f"report_settings tenant_id={self.tenant_id}"
