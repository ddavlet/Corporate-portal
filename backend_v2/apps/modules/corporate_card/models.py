from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class CardExpense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="card_expenses")
    title = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, blank=True, default="UZS")
    expense_at = models.DateTimeField()
    note = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_card_expenses",
    )
    wallet = models.ForeignKey(
        "wallets.Wallet",
        on_delete=models.PROTECT,
        related_name="card_expenses",
    )

    class Meta:
        db_table = "corporate_card_expenses"
        ordering = ["-expense_at", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "expense_at"], name="corp_card_exp_tenant_at_idx"),
        ]


class CardRevenue(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="card_revenues")
    external_id = models.CharField(max_length=64, blank=True, default="")
    confirmed = models.BooleanField(default=True)
    title = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, blank=True, default="UZS")
    revenue_at = models.DateTimeField()
    note = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_card_revenues",
    )
    wallet = models.ForeignKey(
        "wallets.Wallet",
        on_delete=models.PROTECT,
        related_name="card_revenues",
    )

    class Meta:
        db_table = "corporate_card_revenues"
        ordering = ["-revenue_at", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "revenue_at"], name="corp_card_rev_tenant_at_idx"),
        ]
