from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class PayrollDocument(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACCEPTED = "accepted"
    STATUS_CLOSED = "closed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_ACCEPTED, "Принято"),
        (STATUS_CLOSED, "Закрыто"),
        (STATUS_CANCELLED, "Отменено"),
    ]
    SOURCE_PORTAL = "portal"
    SOURCE_N8N = "n8n"
    SOURCE_CHOICES = [(SOURCE_PORTAL, "Портал"), (SOURCE_N8N, "n8n")]
    PAYOUT_MODE_PORTAL = "portal"
    PAYOUT_MODE_LEGACY = "legacy"
    PAYOUT_MODE_CHOICES = [(PAYOUT_MODE_PORTAL, "Через портал"), (PAYOUT_MODE_LEGACY, "Как раньше")]
    KIND_SALARY = "salary"
    KIND_ADVANCE = "advance"
    KIND_BONUS = "bonus"
    KIND_CHOICES = [(KIND_SALARY, "Зарплата"), (KIND_ADVANCE, "Аванс"), (KIND_BONUS, "Премия")]

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
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACCEPTED)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_N8N)
    payout_mode = models.CharField(max_length=16, choices=PAYOUT_MODE_CHOICES, default=PAYOUT_MODE_LEGACY)
    period_month = models.DateField(null=True, blank=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, null=True, blank=True)
    closed_underpaid_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_payroll_documents",
    )
    close_comment = models.TextField(blank=True, default="")

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


class PayrollPayout(models.Model):
    """One employee's share of one cash expense paid out against a payroll document."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="payroll_payouts", db_index=False)
    document = models.ForeignKey(PayrollDocument, on_delete=models.PROTECT, related_name="payouts")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payroll_payouts")
    cash_expense = models.ForeignKey(
        "cashier.CashExpense",
        on_delete=models.PROTECT,
        related_name="payroll_payouts",
        db_index=False,
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payroll_payouts",
    )

    class Meta:
        db_table = "payroll_payouts"
        verbose_name = "Выплата ЗП"
        verbose_name_plural = "Выплаты ЗП"
        constraints = [
            models.UniqueConstraint(fields=["cash_expense", "employee"], name="uniq_payroll_payout_expense_employee"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payroll_payout_amount_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.document_id}:{self.employee_id}:{self.amount}"
