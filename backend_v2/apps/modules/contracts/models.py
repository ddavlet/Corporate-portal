import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant

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


def contract_upload_to(instance: "Contract", filename: str) -> str:
    tenant_part = getattr(instance, "tenant_id", None) or "tmp"
    unique = uuid.uuid4().hex[:16]
    base = os.path.basename(filename or "file").replace("\x00", "").replace("/", "_").replace("\\", "_") or "file"
    return f"contracts/{tenant_part}/{unique}/{base}"


class Contract(models.Model):
    """Tenant contract linked to a vendor directory entry."""

    STATUS_ACCEPTED = "accepted"
    STATUS_REFUSED = "refused"
    STATUS_CHOICES = [
        (STATUS_ACCEPTED, "Принят"),
        (STATUS_REFUSED, "Отказан"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="contracts")
    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    contract_number = models.CharField(max_length=100)
    date_from = models.DateField()
    date_to = models.DateField(null=True, blank=True)
    contract_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=10, default=CURRENCY_UZS, choices=CURRENCY_CHOICES)
    contract_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACCEPTED)
    contract_terms = models.TextField(blank=True, default="")
    contract_file = models.FileField(upload_to=contract_upload_to, max_length=500, null=True, blank=True)
    acc_number = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_contracts",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contracts"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "vendor", "contract_number", "date_from"],
                name="contracts_tenant_vendor_number_date_from_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "vendor"], name="contracts_tenant_vendor_idx"),
            models.Index(fields=["tenant", "contract_status"], name="contracts_tenant_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.contract_number} ({self.tenant_id})"
