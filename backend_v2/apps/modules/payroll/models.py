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
    # Free-text note from the author; appended to the linked Request.description.
    comment = models.TextField(blank=True, default="")

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


# ── Salary card payouts from the Kapitalbank payroll transit account (23106) ──
# Filled by card_sync (statement rows) and card_payouts (links, expected card). Rows are never
# deleted; passport, INN and birth date from the bank directory are never stored.


class BankPayrollEmployee(models.Model):
    """An employee of the bank's payroll project (GetWorkers1C / GetZP1C ``employee_id``)."""

    bank_client_id = models.CharField(max_length=32)
    external_id = models.CharField(max_length=32)
    full_name = models.CharField(max_length=200, blank=True, default="")  # Latin, as the bank sends it
    masked_card = models.CharField(max_length=32, blank=True, default="")
    branch = models.CharField(max_length=5, blank=True, default="")
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_bank_employees"
        constraints = [
            models.UniqueConstraint(
                fields=["bank_client_id", "external_id"], name="uniq_payroll_bank_employee_client_external"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.bank_client_id}:{self.external_id}"


class BankPayrollEmployeeAccount(models.Model):
    """Card account of a bank employee. A reissued card adds a row; old rows stay."""

    SOURCE_WORKERS = "workers"
    SOURCE_ZP = "zp"
    SOURCE_CHOICES = [(SOURCE_WORKERS, "GetWorkers1C"), (SOURCE_ZP, "GetZP1C")]

    bank_employee = models.ForeignKey(BankPayrollEmployee, on_delete=models.PROTECT, related_name="accounts")
    account_no = models.CharField(max_length=20, unique=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_bank_employee_accounts"

    def __str__(self) -> str:
        return f"…{self.account_no[-4:]}"


class PayrollCardBatch(models.Model):
    """Incoming dtype 21 on the transit account: one payroll sheet funded from the tenant's account."""

    transit_account = models.CharField(max_length=20)
    transit_branch = models.CharField(max_length=5, blank=True, default="")
    bank_doc_key = models.CharField(max_length=64)  # general_id, else b2_id
    num = models.CharField(max_length=50, blank=True, default="")
    doc_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    payer_account = models.CharField(max_length=20, blank=True, default="")
    purpose = models.TextField(blank=True, default="")
    period_month = models.DateField()  # first day of the month before doc_date
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name="payroll_card_batches"
    )
    bank_expense = models.ForeignKey(
        "bank_expenses.BankExpense",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_card_batches",
    )
    tenant_resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_card_batches"
        constraints = [
            models.UniqueConstraint(fields=["transit_account", "bank_doc_key"], name="uniq_payroll_card_batch_doc"),
        ]

    def __str__(self) -> str:
        return f"{self.num} {self.doc_date}"


class PayrollCardPayout(models.Model):
    """Outgoing dtype 06 on the transit account: one salary credit to an employee's card."""

    batch = models.ForeignKey(
        PayrollCardBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="payouts"
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name="payroll_card_payouts", db_index=False
    )
    transit_account = models.CharField(max_length=20)
    bank_doc_key = models.CharField(max_length=64)
    card_account = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    paid_on = models.DateField()
    period_month = models.DateField()  # first day of the month before paid_on
    purpose = models.TextField(blank=True, default="")
    name_from_purpose = models.CharField(max_length=200, blank=True, default="")
    bank_employee = models.ForeignKey(
        BankPayrollEmployee, on_delete=models.PROTECT, null=True, blank=True, related_name="payouts"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, null=True, blank=True, related_name="card_payouts"
    )
    employee_assigned_manually = models.BooleanField(default=False)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    document = models.ForeignKey(
        PayrollDocument, on_delete=models.PROTECT, null=True, blank=True, related_name="card_payouts"
    )
    attached_at = models.DateTimeField(null=True, blank=True)
    unassigned_alerted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_card_payouts"
        constraints = [
            models.UniqueConstraint(fields=["transit_account", "bank_doc_key"], name="uniq_payroll_card_payout_doc"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payroll_card_payout_amount_positive"),
        ]
        indexes = [models.Index(fields=["tenant", "period_month"], name="payroll_card_payout_tenant_pm")]

    def __str__(self) -> str:
        return f"{self.paid_on}:{self.amount}"


class PayrollBankEmployeeLink(models.Model):
    """A person confirmed that this bank employee is this portal employee (within the tenant)."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="payroll_bank_employee_links", db_index=False
    )
    bank_employee = models.ForeignKey(BankPayrollEmployee, on_delete=models.PROTECT, related_name="links")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="bank_links")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_bank_employee_links"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "bank_employee"], name="uniq_payroll_bank_employee_link"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.bank_employee_id}->{self.employee_id}"


class PayrollExpectedCard(models.Model):
    """How much of an employee's accrual is expected to arrive on the card (reserved from the cash limit)."""

    document = models.ForeignKey(
        PayrollDocument, on_delete=models.PROTECT, related_name="expected_cards", db_index=False
    )
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="expected_cards")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    is_manual = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_expected_cards"
        constraints = [
            models.UniqueConstraint(fields=["document", "employee"], name="uniq_payroll_expected_card"),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="payroll_expected_card_amount_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document_id}:{self.employee_id}:{self.amount}"


class PayrollCardSettings(models.Model):
    """Per-tenant switch. card_start_period NULL = card payouts are not counted (everything as before)."""

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="payroll_card_settings")
    # First month (day 1) of accruals the card payouts count against; earlier rows are history.
    card_start_period = models.DateField(null=True, blank=True)
    # Close a document when card + cash cover it (fires n8n new-payed-request): off until n8n is checked.
    auto_close_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "payroll_card_settings"

    def save(self, *args, **kwargs):
        # Periods are first days of months: 15.11 in admin means «from November».
        if self.card_start_period is not None:
            self.card_start_period = self.card_start_period.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.tenant_id}: {self.card_start_period or '—'}"
