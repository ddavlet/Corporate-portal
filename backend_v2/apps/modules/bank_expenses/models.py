from django.db import models
from django.conf import settings
from django.utils import timezone

from apps.tenants.models import Tenant


class BankExpense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bank_expenses")
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_bank_expenses",
    )
    row_no = models.IntegerField()
    doc_date = models.DateField()
    process_date = models.DateField()

    doc_no = models.CharField(max_length=50)
    account_name = models.CharField(max_length=255)
    inn = models.CharField(max_length=20, null=True, blank=True)
    account_no = models.CharField(max_length=34)
    mfo = models.CharField(max_length=10)

    debit_turnover = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payment_purpose = models.TextField()
    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_expenses",
    )

    class Meta:
        db_table = "bank_expenses"
        constraints = [
            models.UniqueConstraint(
                fields=["doc_date", "doc_no", "debit_turnover", "payment_purpose"],
                name="uniq_bank_expense_doc_date_doc_no_turnover_purpose",
            )
        ]


class BankRevenue(models.Model):
    # NOTE: "No foreign keys" requirement — we store tenant as plain subdomain.
    tenant_subdomain = models.SlugField(max_length=60)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_bank_revenues",
    )

    row_no = models.IntegerField(null=True, blank=True)
    doc_date = models.DateField()
    process_date = models.DateField()

    doc_no = models.CharField(max_length=50)
    account_name = models.CharField(max_length=255)
    inn = models.CharField(max_length=20)
    account_no = models.CharField(max_length=34)
    mfo = models.CharField(max_length=10)

    kredit_turnover = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payment_purpose = models.TextField()

    class Meta:
        db_table = "bank_revenues"
        constraints = [
            models.UniqueConstraint(
                fields=["doc_no", "doc_date", "kredit_turnover"],
                name="uniq_bank_revenue_doc_no_doc_date_kredit_turnover",
            )
        ]

