from django.db import models
from django.conf import settings

from apps.tenants.models import Tenant


class CashExpense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cash_expenses")
    external_id = models.CharField(max_length=20)
    confirmed = models.BooleanField(default=True)
    title = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, blank=True, default="UZS")
    expense_at = models.DateTimeField()
    expense_year = models.PositiveIntegerField()
    expense_month = models.PositiveSmallIntegerField()
    expense_day = models.PositiveSmallIntegerField()
    note = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_expenses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_cash_expenses",
    )

    class Meta:
        db_table = "cash_expenses"
        ordering = ["-expense_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "external_id", "expense_year"],
                name="cash_expenses_tenant_external_year_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "expense_at"], name="cash_exp_tenant_expense_at_idx"),
            models.Index(fields=["expense_year", "expense_month"], name="cash_exp_year_month_idx"),
        ]


class CashRevenue(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cash_revenues")
    title = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, blank=True, default="UZS")
    revenue_date = models.DateField(null=True, blank=True)
    category = models.CharField(max_length=120, blank=True, default="")
    received_from = models.CharField(max_length=255, blank=True, default="")
    payment_method = models.CharField(max_length=50, blank=True, default="cash")  # cash/card/transfer/other
    reference_no = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(max_length=30, blank=True, default="posted")  # posted/draft/void
    tags = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_cash_revenues",
    )

    class Meta:
        ordering = ["-created_at"]

