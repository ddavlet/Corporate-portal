from django.db import models

from apps.tenants.models import Tenant


class CashExpense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cash_expenses")
    title = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, blank=True, default="UZS")
    expense_date = models.DateField(null=True, blank=True)
    category = models.CharField(max_length=120, blank=True, default="")
    note = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


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

    class Meta:
        ordering = ["-created_at"]

