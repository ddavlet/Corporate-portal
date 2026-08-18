from django.db import models
from django.conf import settings
from django.utils import timezone

from apps.tenants.models import Tenant


class BankExpense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bank_expenses", db_index=False)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_bank_expenses",
    )
    # Stable id from the bank feed / n8n. Empty for legacy rows imported before this field.
    external_id = models.CharField(max_length=64, blank=True, default="")
    row_no = models.IntegerField()
    doc_date = models.DateField()
    process_date = models.DateField()
    expense_year = models.PositiveIntegerField()
    expense_month = models.PositiveSmallIntegerField()
    expense_day = models.PositiveSmallIntegerField()

    doc_no = models.CharField(max_length=50)

    debit_turnover = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payment_purpose = models.TextField()
    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_expenses",
    )
    wallet = models.ForeignKey(
        "wallets.Wallet",
        on_delete=models.PROTECT,
        related_name="bank_expenses",
    )

    class Meta:
        db_table = "bank_expenses"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "doc_date", "doc_no", "debit_turnover", "payment_purpose"],
                name="uniq_bank_expense_tenant_doc_date_doc_no_turnover_purpose",
            ),
            # Gradual replacement for the composite unique above; blank = legacy / unset.
            models.UniqueConstraint(
                fields=["tenant", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_bank_expense_tenant_external_id",
            ),
        ]


class BankRevenue(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bank_revenues", db_index=False)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_bank_revenues",
    )
    external_id = models.CharField(max_length=64, blank=True, default="")

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
    wallet = models.ForeignKey(
        "wallets.Wallet",
        on_delete=models.PROTECT,
        related_name="bank_revenues",
    )

    class Meta:
        db_table = "bank_revenues"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "doc_no", "doc_date", "kredit_turnover"],
                name="uniq_bank_revenue_tenant_doc_no_doc_date_kredit_turnover",
            ),
            models.UniqueConstraint(
                fields=["tenant", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_bank_revenue_tenant_external_id",
            ),
        ]

