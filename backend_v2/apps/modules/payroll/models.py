from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class PayrollDocument(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="payroll_documents", db_index=False)
    doc_id = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payroll_documents",
    )

    class Meta:
        db_table = "payroll_documents"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "doc_id"], name="uniq_payroll_document_tenant_doc_id"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.doc_id}"


class Employee(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="employees", db_index=False)
    full_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_employees",
    )

    class Meta:
        db_table = "payroll_employees"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "full_name"], name="uniq_employee_tenant_full_name"),
        ]

    def __str__(self) -> str:
        return self.full_name


class PayrollLine(models.Model):
    document = models.ForeignKey(
        PayrollDocument,
        on_delete=models.CASCADE,
        related_name="lines",
        db_index=False,
    )
    line_no = models.IntegerField()
    employee = models.TextField()
    employee_fk = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_lines",
    )
    item = models.TextField()
    description = models.TextField(null=True, blank=True)
    sum = models.DecimalField(max_digits=15, decimal_places=2)
    days_plan = models.IntegerField(null=True, blank=True)
    days_fact = models.IntegerField(null=True, blank=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    approval = models.BooleanField(default=False)

    class Meta:
        db_table = "payroll_lines"
        constraints = [
            models.UniqueConstraint(fields=["document", "line_no"], name="uniq_payroll_line_document_line_no"),
        ]

    def __str__(self) -> str:
        return f"{self.document_id}:{self.line_no}"
