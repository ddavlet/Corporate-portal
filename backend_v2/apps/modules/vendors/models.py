from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.tenants.models import Tenant


class Vendor(models.Model):
    """
    Tenant vendor directory: наличные (CASH) or перечисление (TRANSFER).
    ИНН обязателен для TRANSFER и уникален в пределах тенанта.
    """

    KIND_CASH = "cash"
    KIND_TRANSFER = "transfer"
    KIND_CHOICES = [
        (KIND_CASH, "cash"),
        (KIND_TRANSFER, "transfer"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="vendor_directory")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    name = models.CharField(max_length=255)
    inn = models.CharField(max_length=20, null=True, blank=True, verbose_name="ИНН")
    account_number = models.CharField(max_length=34, null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_directory_vendors",
    )

    class Meta:
        db_table = "vendors_directory"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "inn"],
                condition=Q(kind="transfer") & ~Q(inn="") & Q(inn__isnull=False),
                name="vendors_directory_tenant_inn_transfer_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "name", "kind"],
                condition=Q(kind="cash"),
                name="vendors_directory_tenant_name_kind_cash_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "kind"], name="vendors_dir_tenant_kind_idx"),
            models.Index(fields=["tenant", "name"], name="vendors_dir_tenant_name_idx"),
        ]
