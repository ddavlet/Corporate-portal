from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class InvestReturn(models.Model):
    class ReturnType(models.TextChoices):
        DIVIDEND = "дивиденды", "Дивиденды"
        INTEREST = "проценты", "Проценты"
        PROFIT_SHARE = "доля_прибыли", "Доля прибыли"
        PRINCIPAL = "тело_инвестиций", "Тело инвестиций"

    class Recipient(models.TextChoices):
        INVESTOR = "инвестор", "Инвестор"
        PARTNER = "партнер", "Партнер"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invest_returns")
    date = models.DateField()
    sum = models.DecimalField(max_digits=18, decimal_places=2)
    comment = models.TextField(blank=True, default="")
    confirmed = models.BooleanField(default=False)
    currency = models.CharField(max_length=3, default="USD")
    sum_uzs = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    type = models.CharField(max_length=25, choices=ReturnType.choices)
    recipient = models.CharField(max_length=20, choices=Recipient.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invest_returns",
    )

    class Meta:
        db_table = "invest_returns"
        ordering = ["-date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "date"], name="invret_tenant_date_idx"),
            models.Index(fields=["tenant", "confirmed"], name="invret_tenant_conf_idx"),
        ]


class InvestPayoutSchedule(models.Model):
    """Planned investment payouts: due date, amounts, and payment status."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invest_payout_schedules")
    payout_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    is_paid = models.BooleanField(default=False)
    payment_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invest_payout_schedules",
    )

    class Meta:
        db_table = "invest_payout_schedules"
        ordering = ["-payout_date", "-id"]
        indexes = [
            models.Index(fields=["tenant", "payout_date"], name="invsched_tenant_date_idx"),
            models.Index(fields=["tenant", "is_paid"], name="invsched_tenant_paid_idx"),
        ]


class ProjectInvestment(models.Model):
    """Registered capital investment amounts into a project (per tenant)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="project_investments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_project_investments",
    )

    class Meta:
        db_table = "project_investments"
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["tenant", "date"], name="invproj_tenant_date_idx")]
