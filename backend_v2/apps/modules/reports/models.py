from django.db import models

from apps.tenants.models import Tenant


class TenantReportSettings(models.Model):
    """
    Per-tenant configuration for reports (PnL filters, period, etc.).
    Required for per-tenant backend PnL when pnl_source=backend — no code fallbacks if missing.
    """

    PNL_SOURCE_N8N = "n8n"
    PNL_SOURCE_BACKEND = "backend"
    PNL_SOURCE_CHOICES = [
        (PNL_SOURCE_N8N, "n8n"),
        (PNL_SOURCE_BACKEND, "backend"),
    ]

    CASHFLOW_SOURCE_N8N = "n8n"
    CASHFLOW_SOURCE_BACKEND = "backend"
    CASHFLOW_SOURCE_CHOICES = [
        (CASHFLOW_SOURCE_N8N, "n8n"),
        (CASHFLOW_SOURCE_BACKEND, "backend"),
    ]

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="report_settings",
    )
    pnl_source = models.CharField(max_length=16, choices=PNL_SOURCE_CHOICES, default=PNL_SOURCE_N8N)
    pnl_config = models.JSONField(default=dict, blank=True)
    cashflow_source = models.CharField(
        max_length=16,
        choices=CASHFLOW_SOURCE_CHOICES,
        default=CASHFLOW_SOURCE_N8N,
    )
    cashflow_config = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenant_report_settings"

    def __str__(self) -> str:
        return f"report_settings tenant_id={self.tenant_id}"
