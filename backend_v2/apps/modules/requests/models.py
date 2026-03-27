from django.db import models
from django.conf import settings
from django.utils import timezone

from apps.tenants.models import Tenant


class Vendor(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="vendors")
    name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=34, null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_vendors",
    )

    class Meta:
        db_table = "vendors"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_vendor_tenant_name"),
        ]


class Request(models.Model):
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

    PAYMENT_TYPE_CASH = "Наличные"
    PAYMENT_TYPE_TRANSFER = "Перечисление"
    PAYMENT_TYPE_TOPUP = "Пополнение"
    PAYMENT_TYPE_CARD = "Платежная карта"
    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_TYPE_CASH, PAYMENT_TYPE_CASH),
        (PAYMENT_TYPE_TRANSFER, PAYMENT_TYPE_TRANSFER),
        (PAYMENT_TYPE_TOPUP, PAYMENT_TYPE_TOPUP),
        (PAYMENT_TYPE_CARD, PAYMENT_TYPE_CARD),
    ]

    URGENCY_LOW = "Низко"
    URGENCY_NORMAL = "Обычно"
    URGENCY_HIGH = "Срочно"
    URGENCY_CHOICES = [
        (URGENCY_LOW, URGENCY_LOW),
        (URGENCY_NORMAL, URGENCY_NORMAL),
        (URGENCY_HIGH, URGENCY_HIGH),
    ]

    STATUS_DRAFT = "DRAFT"
    STATUS_PROGRESS_1 = "1"
    STATUS_PROGRESS_2 = "2"
    STATUS_PROGRESS_3 = "3"
    STATUS_PROGRESS_4 = "4"
    STATUS_PROGRESS_5 = "5"
    STATUS_APPROVED = "APPROVED"
    STATUS_PAYED = "PAYED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, STATUS_DRAFT),
        (STATUS_PROGRESS_1, STATUS_PROGRESS_1),
        (STATUS_PROGRESS_2, STATUS_PROGRESS_2),
        (STATUS_PROGRESS_3, STATUS_PROGRESS_3),
        (STATUS_PROGRESS_4, STATUS_PROGRESS_4),
        (STATUS_PROGRESS_5, STATUS_PROGRESS_5),
        (STATUS_APPROVED, STATUS_APPROVED),
        (STATUS_PAYED, STATUS_PAYED),
        (STATUS_REJECTED, STATUS_REJECTED),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="requests")
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_requests",
    )

    company_payer = models.CharField(max_length=100, default="")
    category = models.CharField(max_length=100, default="")
    vendor = models.CharField(max_length=150, default="")

    title = models.CharField(max_length=200, default="")
    description = models.TextField(default="")

    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default=CURRENCY_UZS, choices=CURRENCY_CHOICES)

    payment_type = models.CharField(max_length=50, default=PAYMENT_TYPE_CASH, choices=PAYMENT_TYPE_CHOICES)
    urgency = models.CharField(max_length=50, default=URGENCY_NORMAL, choices=URGENCY_CHOICES)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_items",
        null=True,
        blank=True,
    )

    payment_purpose = models.CharField(max_length=200, default="")

    submitted_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=50, default=STATUS_DRAFT, choices=STATUS_CHOICES)

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


class Approval(models.Model):
    STEP_TYPE_SERIAL = "serial"
    STEP_TYPE_PAYMENT = "payment"
    STEP_TYPE_CHOICES = [
        (STEP_TYPE_SERIAL, STEP_TYPE_SERIAL),
        (STEP_TYPE_PAYMENT, STEP_TYPE_PAYMENT),
    ]

    DECISION_PENDING = "pending"
    DECISION_APPROVED = "approved"
    DECISION_REJECTED = "rejected"
    DECISION_CHOICES = [
        (DECISION_PENDING, DECISION_PENDING),
        (DECISION_APPROVED, DECISION_APPROVED),
        (DECISION_REJECTED, DECISION_REJECTED),
    ]

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="approvals")
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="request_approvals",
    )
    approver_tg_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    message_sent = models.BooleanField(default=False)
    step = models.IntegerField(default=1)
    step_type = models.CharField(max_length=10, default=STEP_TYPE_SERIAL, choices=STEP_TYPE_CHOICES)
    decision = models.CharField(max_length=12, default=DECISION_PENDING, choices=DECISION_CHOICES)
    comment = models.TextField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approvals"
        constraints = [
            models.UniqueConstraint(
                fields=["request", "step", "approver_user"],
                name="approvals_request_step_approver_user_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["request"], name="approvals_request_id_idx"),
            models.Index(fields=["decision"], name="approvals_decision_idx"),
            models.Index(fields=["approver_tg_id"], name="approvals_approver_tg_id_idx"),
            models.Index(fields=["message_sent"], name="approvals_message_sent_idx"),
        ]


class RequestFormConfig(models.Model):
    """
    Tenant-level configuration for adaptive request-create form.
    """

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="request_form_config")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_request_form_configs",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "request_form_configs"


class RequestFormPaymentTypeConfig(models.Model):
    config = models.ForeignKey(RequestFormConfig, on_delete=models.CASCADE, related_name="payment_types")
    payment_type = models.CharField(max_length=50, choices=Request.PAYMENT_TYPE_CHOICES)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "request_form_payment_type_configs"
        constraints = [
            models.UniqueConstraint(
                fields=["config", "payment_type"],
                name="req_form_payment_type_config_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["config", "payment_type"], name="req_form_pt_cfg_idx"),
            models.Index(fields=["is_enabled"], name="req_form_pt_enabled_idx"),
        ]


class RequestFormPaymentTypeRequester(models.Model):
    payment_type_config = models.ForeignKey(
        RequestFormPaymentTypeConfig,
        on_delete=models.CASCADE,
        related_name="allowed_requesters",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="request_form_allowed_in_payment_types",
    )

    class Meta:
        db_table = "request_form_payment_type_requesters"
        constraints = [
            models.UniqueConstraint(
                fields=["payment_type_config", "user"],
                name="req_form_pt_requester_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["payment_type_config"], name="req_form_pt_req_cfg_idx"),
            models.Index(fields=["user"], name="req_form_pt_req_user_idx"),
        ]


class RequestFormPaymentTypeVendor(models.Model):
    payment_type_config = models.ForeignKey(
        RequestFormPaymentTypeConfig,
        on_delete=models.CASCADE,
        related_name="allowed_vendors",
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name="request_form_allowed_in_payment_types",
    )

    class Meta:
        db_table = "request_form_payment_type_vendors"
        constraints = [
            models.UniqueConstraint(
                fields=["payment_type_config", "vendor"],
                name="req_form_pt_vendor_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["payment_type_config"], name="req_form_pt_vendor_cfg_idx"),
            models.Index(fields=["vendor"], name="req_form_pt_vendor_vendor_idx"),
        ]


class RequestPaymentPurposeConfig(models.Model):
    payment_type_config = models.ForeignKey(
        RequestFormPaymentTypeConfig,
        on_delete=models.CASCADE,
        related_name="payment_purposes",
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "request_payment_purpose_configs"
        constraints = [
            models.UniqueConstraint(
                fields=["payment_type_config", "name"],
                name="req_form_pt_purpose_name_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["payment_type_config"], name="req_form_purpose_cfg_idx"),
            models.Index(fields=["is_active"], name="req_form_purpose_active_idx"),
        ]
