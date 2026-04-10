from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class ClientDebtSnapshot(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="client_debt_snapshots")
    snapshot_at = models.DateTimeField()
    doc_type = models.CharField(max_length=64, default="client_debt_total")
    organization = models.CharField(max_length=200, blank=True, default="")
    client = models.CharField(max_length=255, blank=True, default="")
    client_id = models.CharField(max_length=64, blank=True, default="")
    debt_sum = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    quantity = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    cert_discount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_client_debt_snapshots",
    )

    class Meta:
        db_table = "clients_debt_snapshots"
        ordering = ["-snapshot_at", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "snapshot_at", "doc_type", "client_id"],
                name="clients_debt_tenant_date_type_client_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "snapshot_at"], name="clients_debt_tenant_date_idx"),
            models.Index(fields=["tenant", "client_id"], name="clients_debt_tenant_client_idx"),
            models.Index(fields=["tenant", "doc_type"], name="clients_debt_tenant_type_idx"),
        ]

