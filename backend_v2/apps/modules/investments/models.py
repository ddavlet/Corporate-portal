from decimal import Decimal
import secrets

from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class InvestReturn(models.Model):
    class ReturnType(models.TextChoices):
        DIVIDEND = "дивиденды", "Дивиденды"
        INTEREST = "проценты", "Проценты"
        PROFIT_SHARE = "доля_прибыли", "Доля прибыли"
        PRINCIPAL = "тело_инвестиций", "Тело инвестиций"

    class Recipient(models.TextChoices):
        INVESTOR = "инвестор", "Инвестор"
        PARTNER = "партнер", "Партнер"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invest_returns")
    company = models.ForeignKey(
        "InvestCompany",
        on_delete=models.SET_NULL,
        related_name="returns",
        null=True,
        blank=True,
    )
    date = models.DateField()
    sum = models.DecimalField(max_digits=18, decimal_places=2)
    comment = models.TextField(blank=True, default="")
    confirmed = models.BooleanField(default=False)
    currency = models.CharField(max_length=3, default="USD")
    sum_uzs = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    type = models.CharField(max_length=25, choices=ReturnType.choices)
    recipient = models.CharField(max_length=20, choices=Recipient.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invest_returns",
    )

    class Meta:
        db_table = "invest_returns"
        ordering = ["-date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "date"], name="invret_tenant_date_idx"),
            models.Index(fields=["tenant", "confirmed"], name="invret_tenant_conf_idx"),
        ]


class InvestPayoutSchedule(models.Model):
    """Planned investment payouts: due date, amounts, and payment status."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invest_payout_schedules")
    company = models.ForeignKey(
        "InvestCompany",
        on_delete=models.SET_NULL,
        related_name="payout_schedules",
        null=True,
        blank=True,
    )
    payout_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    is_paid = models.BooleanField(default=False)
    payment_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invest_payout_schedules",
    )

    class Meta:
        db_table = "invest_payout_schedules"
        ordering = ["-payout_date", "-id"]
        indexes = [
            models.Index(fields=["tenant", "payout_date"], name="invsched_tenant_date_idx"),
            models.Index(fields=["tenant", "is_paid"], name="invsched_tenant_paid_idx"),
        ]


class ProjectInvestment(models.Model):
    """Registered capital investment amounts into a project (per tenant)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="project_investments")
    company = models.ForeignKey(
        "InvestCompany",
        on_delete=models.SET_NULL,
        related_name="project_investments",
        null=True,
        blank=True,
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_project_investments",
    )

    class Meta:
        db_table = "project_investments"
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["tenant", "date"], name="invproj_tenant_date_idx")]


class InvestCompany(models.Model):
    """Company/legal entity dimension for investments inside one tenant."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invest_companies")
    name = models.CharField(max_length=255)
    comment = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invest_companies",
    )

    class Meta:
        db_table = "invest_companies"
        ordering = ["name", "id"]
        unique_together = [("tenant", "name")]
        indexes = [models.Index(fields=["tenant", "is_active"], name="invco_tenant_active_idx")]


class InvestPayoutScheduleShareLink(models.Model):
    """Public read-only link for filtered payout schedule viewing."""

    class PaidFilter(models.TextChoices):
        ALL = "all", "All"
        PAID = "paid", "Paid"
        UNPAID = "unpaid", "Unpaid"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invest_schedule_share_links")
    token = models.CharField(max_length=64, unique=True, db_index=True)
    company = models.ForeignKey(
        "InvestCompany",
        on_delete=models.SET_NULL,
        related_name="schedule_share_links",
        null=True,
        blank=True,
    )
    paid_filter = models.CharField(max_length=10, choices=PaidFilter.choices, default=PaidFilter.ALL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invest_schedule_share_links",
    )

    class Meta:
        db_table = "invest_payout_schedule_share_links"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "is_active"], name="invslink_tenant_active_idx"),
            models.Index(fields=["tenant", "company"], name="invslink_tenant_comp_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)


class InvestmentApprovalConfig(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="investment_approval_config")
    is_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "investment_approval_config"


class InvestmentApprovalConfigStep(models.Model):
    STEP_TYPE_SERIAL = "serial"
    STEP_TYPE_CONFIRMATION = "confirmation"
    STEP_TYPE_CHOICES = [
        (STEP_TYPE_SERIAL, STEP_TYPE_SERIAL),
        (STEP_TYPE_CONFIRMATION, STEP_TYPE_CONFIRMATION),
    ]

    config = models.ForeignKey(InvestmentApprovalConfig, on_delete=models.CASCADE, related_name="steps")
    step = models.PositiveIntegerField()
    step_type = models.CharField(max_length=16, choices=STEP_TYPE_CHOICES, default=STEP_TYPE_SERIAL)
    is_enabled = models.BooleanField(default=True)
    payment_chat_id = models.BigIntegerField(null=True, blank=True)
    approver_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="InvestmentApprovalConfigStepApprover",
        related_name="investment_approval_steps",
    )

    class Meta:
        db_table = "investment_approval_config_steps"
        ordering = ["step", "id"]
        unique_together = [("config", "step")]
        indexes = [models.Index(fields=["config", "step"], name="invcfg_step_cfg_step_idx")]


class InvestmentApprovalConfigStepApprover(models.Model):
    step = models.ForeignKey(InvestmentApprovalConfigStep, on_delete=models.CASCADE, related_name="step_approvers")
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="investment_step_assignments",
    )

    class Meta:
        db_table = "investment_approval_config_step_approvers"
        unique_together = [("step", "approver_user")]
        indexes = [
            models.Index(fields=["step", "approver_user"], name="invcfg_step_appr_idx"),
        ]


class InvestmentReturnApproval(models.Model):
    DECISION_PENDING = "pending"
    DECISION_APPROVED = "approved"
    DECISION_REJECTED = "rejected"
    DECISION_CHOICES = [
        (DECISION_PENDING, "Pending"),
        (DECISION_APPROVED, "Approved"),
        (DECISION_REJECTED, "Rejected"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="investment_return_approvals")
    invest_return = models.ForeignKey(InvestReturn, on_delete=models.CASCADE, related_name="approvals")
    step = models.PositiveIntegerField()
    step_type = models.CharField(
        max_length=16,
        choices=InvestmentApprovalConfigStep.STEP_TYPE_CHOICES,
        default=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
    )
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="investment_return_approvals",
    )
    approver_recipient_id = models.BigIntegerField(null=True, blank=True)
    approver_external_user_id = models.BigIntegerField(null=True, blank=True)
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default=DECISION_PENDING)
    decision_comment = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    gateway_message_id = models.BigIntegerField(null=True, blank=True)
    message_sent = models.BooleanField(default=False)
    message_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "investment_return_approvals"
        ordering = ["step", "id"]
        unique_together = [("invest_return", "step", "approver_user")]
        indexes = [
            models.Index(fields=["tenant", "invest_return"], name="invrapp_tenant_ret_idx"),
            models.Index(fields=["tenant", "decision"], name="invrapp_tenant_dec_idx"),
            models.Index(fields=["approver_recipient_id"], name="invrapp_recipient_idx"),
            models.Index(fields=["gateway_message_id"], name="invrapp_gateway_msg_idx"),
        ]
