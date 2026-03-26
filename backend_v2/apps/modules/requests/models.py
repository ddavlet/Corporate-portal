from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class Request(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="requests")

    company_payer = models.CharField(max_length=100, default="")
    category = models.CharField(max_length=100, default="")
    vendor = models.CharField(max_length=150, default="")

    title = models.CharField(max_length=200, default="")
    description = models.TextField(default="")

    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="UZS")

    payment_type = models.CharField(max_length=50, default="")
    urgency = models.CharField(max_length=50, default="")
    requester = models.CharField(max_length=100, default="")

    payment_purpose = models.CharField(max_length=200, default="")

    submitted_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=50, default="DRAFT")

    payed_at = models.IntegerField(null=True, blank=True)

    # Polymorphic string id pointing to expenses modules (cash/bank) or external systems.
    expense_id = models.CharField(max_length=20, null=True, blank=True)
    file_link = models.TextField(null=True, blank=True)

    expense_year = models.IntegerField(null=True, blank=True)
    expense_month = models.IntegerField(null=True, blank=True)
    expense_day = models.IntegerField(null=True, blank=True)

    billing_date = models.DateField()

    class Meta:
        db_table = "requests"

