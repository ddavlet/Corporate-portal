from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from decimal import Decimal

from apps.tenants.models import Tenant


class Budget(models.Model):
    PERIOD_MONTHLY = "monthly"
    PERIOD_QUARTERLY = "quarterly"
    PERIOD_YEARLY = "yearly"
    PERIOD_CHOICES = [
        (PERIOD_MONTHLY, "Ежемесячно"),
        (PERIOD_QUARTERLY, "Ежеквартально"),
        (PERIOD_YEARLY, "Ежегодно"),
    ]

    CURRENCY_UZS = "UZS"
    CURRENCY_USD = "USD"
    CURRENCY_EUR = "EUR"
    CURRENCY_RUB = "RUB"
    CURRENCY_CHOICES = [
        (CURRENCY_UZS, CURRENCY_UZS),
        (CURRENCY_USD, CURRENCY_USD),
        (CURRENCY_EUR, CURRENCY_EUR),
        (CURRENCY_RUB, CURRENCY_RUB),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="budgets")
    name = models.CharField(max_length=255)
    # FK to RequestCategory — Option B: referential integrity on the budget side.
    # Spend queries match by category.name since Request.category is a CharField.
    category = models.ForeignKey(
        "requests.RequestCategory",
        on_delete=models.PROTECT,
        related_name="budgets",
    )
    period_type = models.CharField(max_length=20, choices=PERIOD_CHOICES)
    limit_amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField(max_length=3, default=CURRENCY_UZS, choices=CURRENCY_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_budgets",
    )

    class Meta:
        db_table = "budgets"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="budgets_tenant_name_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "is_active"], name="budgets_tenant_active_idx"),
            models.Index(fields=["tenant", "category"], name="budgets_tenant_category_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.tenant})"
