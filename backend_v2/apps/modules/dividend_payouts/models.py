from django.db import models
from django.db.models.functions import Lower

from apps.modules.investments.models import InvestReturn
from apps.tenants.models import Tenant


class DividendPayoutRule(models.Model):
    """Tenant rule: a PAYED request with this payment purpose creates an InvestReturn of the given type/recipient."""

    # The (tenant, lower(payment_purpose)) unique index leads with tenant, so no separate FK index.
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="dividend_payout_rules", db_index=False)
    payment_purpose = models.CharField(max_length=200)
    return_type = models.CharField(max_length=25, choices=InvestReturn.ReturnType.choices)
    recipient = models.CharField(max_length=20, choices=InvestReturn.Recipient.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "dividend_payout_rules"
        constraints = [
            models.UniqueConstraint("tenant", Lower("payment_purpose"), name="dividend_rule_tenant_purpose_uniq"),
        ]

    def __str__(self):
        return f"DividendPayoutRule(tenant={self.tenant_id}, purpose={self.payment_purpose!r})"


class DividendPayoutLink(models.Model):
    """One row per request: makes the PAYED handler idempotent and records the outcome."""

    class Status(models.TextChoices):
        CREATED = "created", "Выплата создана"
        FAILED = "failed", "Ошибка"

    request = models.OneToOneField(
        "requests.Request", on_delete=models.CASCADE, related_name="dividend_payout_link"
    )
    invest_return = models.ForeignKey(
        "investments.InvestReturn",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dividend_payout_links",
    )
    rule = models.ForeignKey(
        DividendPayoutRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="links",
    )
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dividend_payout_links"

    def __str__(self):
        return f"DividendPayoutLink(request={self.request_id}, status={self.status})"
