from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class CardExpense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="card_expenses", db_index=False)
    external_id = models.CharField(max_length=64, blank=True, default="")
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
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_card_expense_tenant_external_id",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "expense_at"], name="corp_card_exp_tenant_at_idx"),
        ]


class CardRevenue(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="card_revenues", db_index=False)
    external_id = models.CharField(max_length=64, blank=True, default="")
    confirmed = models.BooleanField(default=True)
    operation = models.CharField(max_length=255, blank=True, default="")
    counterparty = models.CharField(max_length=255, blank=True, default="")
    total_sum = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    comment = models.TextField(blank=True, default="")
    currency = models.CharField(max_length=10, blank=True, default="UZS")
    revenue_at = models.DateTimeField()
    payload = models.JSONField(default=dict, blank=True)
    # Soft link to bank expense by ID, intentionally without FK.
    bank_expense_id = models.BigIntegerField(null=True, blank=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_card_revenue_tenant_external_id",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "revenue_at"], name="corp_card_rev_tenant_at_idx"),
            models.Index(fields=["tenant", "bank_expense_id"], name="corp_card_rev_bank_id_idx"),
        ]


class CardExpenseAutoRequestConfig(models.Model):
    """Per-card template: every new CardExpense without a request gets one PAYED «Платежная карта» request."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="card_expense_auto_request_configs",
        db_index=False,
    )
    wallet = models.OneToOneField(
        "wallets.Wallet",
        on_delete=models.CASCADE,
        related_name="card_auto_request_config",
    )
    is_enabled = models.BooleanField(default=False)
    payment_purpose = models.CharField(max_length=200, blank=True, default="")
    category = models.CharField(max_length=100, blank=True, default="")
    company_payer = models.CharField(max_length=100, blank=True, default="")
    vendor_ref = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="card_expense_auto_request_configs",
    )
    match_text = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="updated_card_expense_auto_request_configs",
    )

    class Meta:
        db_table = "corporate_card_auto_request_configs"
        indexes = [
            models.Index(fields=["tenant", "is_enabled"], name="corp_card_autoreq_tnt_en_idx"),
        ]

    def __str__(self):
        return f"CardExpenseAutoRequestConfig(wallet={self.wallet_id}, enabled={self.is_enabled})"

