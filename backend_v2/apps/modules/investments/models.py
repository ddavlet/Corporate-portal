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
    type = models.CharField(max_length=25, choices=ReturnType.choices)
    recipient = models.CharField(max_length=20, choices=Recipient.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invest_returns",
    )

    class Meta:
        db_table = "invest_returns"
        ordering = ["-date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "date"], name="invest_returns_tenant_date_idx"),
            models.Index(fields=["tenant", "confirmed"], name="invest_returns_tenant_confirmed_idx"),
        ]
