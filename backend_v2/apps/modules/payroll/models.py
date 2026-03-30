from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class PayrollDocument(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="payroll_documents")
    doc_id = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_documents"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "doc_id"], name="uniq_payroll_document_tenant_doc_id"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.doc_id}"


class PayrollLine(models.Model):
    document = models.ForeignKey(
        PayrollDocument,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    line_no = models.IntegerField()
    employee = models.TextField()
    item = models.TextField()
    description = models.TextField(null=True, blank=True)
    sum = models.DecimalField(max_digits=15, decimal_places=2)
    days_plan = models.IntegerField()
    days_fact = models.IntegerField()
    period_start = models.DateField()
    period_end = models.DateField()
    approval = models.BooleanField(default=False)

    class Meta:
        db_table = "payroll_lines"
        constraints = [
            models.UniqueConstraint(fields=["document", "line_no"], name="uniq_payroll_line_document_line_no"),
        ]

    def __str__(self) -> str:
        return f"{self.document_id}:{self.line_no}"
