import uuid

from django.db import models
from django.conf import settings
from django.utils import timezone

from apps.tenants.models import Tenant


class RequestQuerySet(models.QuerySet):
    def exclude_deleted(self):
        return self.exclude(status=Request.STATUS_DELETED)


class ActiveRequestManager(models.Manager.from_queryset(RequestQuerySet)):
    def get_queryset(self):
        return super().get_queryset().exclude_deleted()


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
    PAYMENT_TYPE_PAYROLL = "Начисление ЗП"
    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_TYPE_CASH, PAYMENT_TYPE_CASH),
        (PAYMENT_TYPE_TRANSFER, PAYMENT_TYPE_TRANSFER),
        (PAYMENT_TYPE_TOPUP, PAYMENT_TYPE_TOPUP),
        (PAYMENT_TYPE_CARD, PAYMENT_TYPE_CARD),
        (PAYMENT_TYPE_PAYROLL, PAYMENT_TYPE_PAYROLL),
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
    STATUS_DELETED = "DELETED"
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
        (STATUS_DELETED, STATUS_DELETED),
    ]

    # Distinguishes which table `expense_ref_id` points to (PKs can collide across modules).
    EXPENSE_REF_TARGET_CASH = "cash"
    EXPENSE_REF_TARGET_PAYROLL = "payroll"
    EXPENSE_REF_TARGET_BANK = "bank"
    EXPENSE_REF_TARGET_CARD = "card"
    EXPENSE_REF_TARGET_CHOICES = [
        (EXPENSE_REF_TARGET_CASH, EXPENSE_REF_TARGET_CASH),
        (EXPENSE_REF_TARGET_PAYROLL, EXPENSE_REF_TARGET_PAYROLL),
        (EXPENSE_REF_TARGET_BANK, EXPENSE_REF_TARGET_BANK),
        (EXPENSE_REF_TARGET_CARD, EXPENSE_REF_TARGET_CARD),
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
    vendor_ref = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests",
    )
    contract_ref = models.ForeignKey(
        "contracts.Contract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests",
    )

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

    # Transport/business key from external payloads (kept for backward-compatible API contracts).
    expense_id = models.CharField(max_length=200, null=True, blank=True)
    # Canonical reference to expense document primary key across payment modules.
    expense_ref_id = models.BigIntegerField(null=True, blank=True)
    expense_ref_target = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        choices=EXPENSE_REF_TARGET_CHOICES,
    )
    file_link = models.TextField(null=True, blank=True)

    expense_year = models.IntegerField(null=True, blank=True)
    expense_month = models.IntegerField(null=True, blank=True)
    expense_day = models.IntegerField(null=True, blank=True)

    # Cross-tenant copy origin (set only via the n8n import path). Non-null marks this
    # request as a copy of a request living in another tenant that shares the same bank account.
    source_tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="copied_out_requests",
    )
    source_request_id = models.BigIntegerField(null=True, blank=True)

    # Set via the n8n callback when the original (source_tenant is null) request's expense
    # was matched to a bank expense in another tenant's data, so its own red/missing-expense
    # row can be cleared without a local expense_ref.
    external_matched_tenant = models.ForeignKey(
        Tenant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="externally_matched_requests",
    )
    external_matched_at = models.DateTimeField(null=True, blank=True)

    billing_date = models.DateField()
    amortization_months = models.PositiveIntegerField(default=1)
    amortization_start_date = models.DateField(null=True, blank=True)

    objects = ActiveRequestManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "requests"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_tenant", "source_request_id"],
                name="req_tenant_source_req_uniq",
                condition=models.Q(source_tenant__isnull=False, source_request_id__isnull=False),
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "payment_type", "payment_purpose"],
                name="req_tenant_pt_purpose_idx",
                condition=models.Q(payment_purpose__gt=""),
            ),
            models.Index(fields=["tenant", "submitted_at", "id"], name="req_tenant_submitted_id_idx"),
            models.Index(fields=["tenant", "status", "submitted_at"], name="req_tnt_stat_submitted_idx"),
        ]

    def _resolve_title_from_tenant(self) -> str:
        tenant_name = ""
        tenant_obj = getattr(self, "tenant", None)
        if tenant_obj is not None:
            tenant_name = str(getattr(tenant_obj, "name", "") or "").strip()
        if not tenant_name and self.tenant_id:
            tenant_name = (
                Tenant.objects.filter(id=self.tenant_id).values_list("name", flat=True).first() or ""
            ).strip()
        return tenant_name[:200]

    def save(self, *args, **kwargs):
        self.title = self._resolve_title_from_tenant()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields_set = set(update_fields)
            update_fields_set.add("title")
            kwargs["update_fields"] = list(update_fields_set)
        return super().save(*args, **kwargs)


class RequestAttachment(models.Model):
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="attachments")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="request_attachments")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="request_attachments",
    )
    file_path = models.TextField()
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "request_attachments"
        indexes = [
            models.Index(fields=["tenant", "request"], name="req_att_tenant_req_idx"),
            models.Index(fields=["request", "created_at"], name="req_att_req_created_idx"),
        ]


class Approval(models.Model):
    STEP_TYPE_SERIAL = "serial"
    STEP_TYPE_PAYMENT = "payment"
    STEP_TYPE_NOTIFICATION = "notification"
    STEP_TYPE_CHOICES = [
        (STEP_TYPE_SERIAL, STEP_TYPE_SERIAL),
        (STEP_TYPE_PAYMENT, STEP_TYPE_PAYMENT),
        (STEP_TYPE_NOTIFICATION, STEP_TYPE_NOTIFICATION),
    ]

    DECISION_PENDING = "pending"
    DECISION_APPROVED = "approved"
    DECISION_REJECTED = "rejected"
    DECISION_CANCELED = "canceled"
    DECISION_CHOICES = [
        (DECISION_PENDING, DECISION_PENDING),
        (DECISION_APPROVED, DECISION_APPROVED),
        (DECISION_REJECTED, DECISION_REJECTED),
        (DECISION_CANCELED, DECISION_CANCELED),
    ]

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="approvals")
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="request_approvals",
    )
    approver_recipient_id = models.CharField(max_length=50, null=True, blank=True)
    # Platform user id (e.g. Telegram from.id); distinct from FK `approver_user` / `approver_user_id`.
    approver_external_user_id = models.BigIntegerField(null=True, blank=True)
    telegram_message = models.OneToOneField(
        "telegram_approvals.TelegramMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="request_approval",
    )
    step = models.IntegerField(default=1)
    step_type = models.CharField(max_length=16, default=STEP_TYPE_SERIAL, choices=STEP_TYPE_CHOICES)
    decision = models.CharField(max_length=12, default=DECISION_PENDING, choices=DECISION_CHOICES)
    resend_batch_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    resend_key = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    replaced_approval = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="resend_children"
    )
    comment = models.TextField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approvals"
        constraints = [
            models.UniqueConstraint(
                fields=["request", "step", "approver_user", "resend_batch_id"],
                name="approvals_req_step_user_batch_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["request"], name="approvals_request_id_idx"),
            models.Index(fields=["decision"], name="approvals_decision_idx"),
            models.Index(fields=["approver_recipient_id"], name="approvals_appr_rcpt_idx"),
            models.Index(fields=["approver_external_user_id"], name="approvals_ext_uid_idx"),
        ]

    # --- Derived read-only accessors -------------------------------------------------
    # The single source of truth for a sent approval card is `telegram_message`
    # (a TelegramMessage row). These properties keep the historical field names working
    # for readers (API, callers) without storing duplicate data on the approval.
    @property
    def gateway_message_id(self):
        tm = self.telegram_message
        return tm.message_id if tm else None

    @property
    def message_sent(self) -> bool:
        return self.telegram_message_id is not None

    @property
    def message_sent_at(self):
        tm = self.telegram_message
        return tm.sent_at if tm else None


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


class RequestCategory(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="request_categories")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "request_categories"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="request_category_tenant_name_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "is_active"], name="req_cat_tenant_active_idx"),
            models.Index(fields=["tenant", "name"], name="req_cat_tenant_name_idx"),
        ]


class RequestFormPaymentTypeConfig(models.Model):
    config = models.ForeignKey(RequestFormConfig, on_delete=models.CASCADE, related_name="payment_types")
    payment_type = models.CharField(max_length=50, choices=Request.PAYMENT_TYPE_CHOICES)
    is_enabled = models.BooleanField(default=True)

    default_title = models.CharField(max_length=200, default="")
    default_company_payer = models.CharField(max_length=100, default="")
    default_description = models.TextField(default="")
    default_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    default_currency = models.CharField(max_length=10, default=Request.CURRENCY_UZS)
    default_urgency = models.CharField(max_length=50, default=Request.URGENCY_NORMAL)
    default_billing_days_offset = models.IntegerField(default=0)
    default_payment_purpose = models.CharField(max_length=200, default="", blank=True)
    default_vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_form_default_for_payment_types",
    )
    contracts_required = models.BooleanField(default=False)

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
        "vendors.Vendor",
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


class RequestApprovalConfig(models.Model):
    """
    Tenant-level configuration of request approvals.

    Design goal:
    - config depends only on `Request.payment_type`
    - approval steps depend on config and contain explicit approver user list
    """

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="request_approval_config")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_request_approval_configs",
        null=True,
        blank=True,
    )
    comment_webapp_url = models.TextField(blank=True, default="")

    class Meta:
        db_table = "request_approval_configs"


class RequestApprovalPaymentTypeConfig(models.Model):
    config = models.ForeignKey(RequestApprovalConfig, on_delete=models.CASCADE, related_name="payment_types")
    payment_type = models.CharField(max_length=50, choices=Request.PAYMENT_TYPE_CHOICES)
    is_enabled = models.BooleanField(default=True)
    request_not_required_rules = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "request_approval_payment_type_configs"
        constraints = [
            models.UniqueConstraint(fields=["config", "payment_type"], name="req_appr_pt_cfg_uniq"),
        ]
        indexes = [
            models.Index(fields=["config", "payment_type"], name="req_appr_pt_cfg_idx"),
            models.Index(fields=["is_enabled"], name="req_appr_pt_enabled_idx"),
        ]


class RequestApprovalStepConfig(models.Model):
    PAYMENT_ACTION_MODE_CALLBACK = "callback"
    PAYMENT_ACTION_MODE_WEBAPP = "webapp"
    PAYMENT_ACTION_MODE_CREATE = "create"
    PAYMENT_ACTION_MODE_CHOICES = [
        (PAYMENT_ACTION_MODE_CALLBACK, PAYMENT_ACTION_MODE_CALLBACK),
        (PAYMENT_ACTION_MODE_WEBAPP, PAYMENT_ACTION_MODE_WEBAPP),
        (PAYMENT_ACTION_MODE_CREATE, PAYMENT_ACTION_MODE_CREATE),
    ]

    payment_type_config = models.ForeignKey(
        RequestApprovalPaymentTypeConfig, on_delete=models.CASCADE, related_name="steps"
    )
    step = models.IntegerField()
    step_type = models.CharField(max_length=16, choices=Approval.STEP_TYPE_CHOICES, default=Approval.STEP_TYPE_SERIAL)
    is_enabled = models.BooleanField(default=True)
    payment_action_mode = models.CharField(
        max_length=12,
        choices=PAYMENT_ACTION_MODE_CHOICES,
        default=PAYMENT_ACTION_MODE_CALLBACK,
    )
    payment_webapp_url = models.TextField(blank=True, default="")
    telegram_chat = models.ForeignKey(
        "telegram_approvals.TenantTelegramChat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_approval_steps",
    )

    class Meta:
        db_table = "request_approval_step_configs"
        constraints = [
            models.UniqueConstraint(fields=["payment_type_config", "step"], name="req_appr_step_uniq"),
        ]
        indexes = [
            models.Index(fields=["payment_type_config", "step"], name="req_appr_step_idx"),
            models.Index(fields=["payment_type_config"], name="req_appr_steps_by_pt_idx"),
        ]


class RequestApprovalStepApproverConfig(models.Model):
    step_config = models.ForeignKey(RequestApprovalStepConfig, on_delete=models.CASCADE, related_name="approvers")
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="request_approval_step_approver_configs",
    )

    class Meta:
        db_table = "request_approval_step_approver_configs"
        constraints = [
            models.UniqueConstraint(fields=["step_config", "approver_user"], name="req_appr_step_approver_uniq"),
        ]
        indexes = [
            models.Index(fields=["step_config"], name="req_appr_step_approvers_idx"),
        ]


class RequestApprovalPurposeExceptionConfig(models.Model):
    payment_type_config = models.ForeignKey(
        RequestApprovalPaymentTypeConfig,
        on_delete=models.CASCADE,
        related_name="purpose_exceptions",
    )
    name = models.CharField(max_length=200, default="", blank=True)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "request_approval_purpose_exception_configs"
        indexes = [
            models.Index(fields=["payment_type_config"], name="req_appr_exc_pt_idx"),
            models.Index(fields=["payment_type_config", "is_enabled"], name="req_appr_exc_enabled_idx"),
        ]


class RequestApprovalPurposeExceptionPurpose(models.Model):
    exception_config = models.ForeignKey(
        RequestApprovalPurposeExceptionConfig,
        on_delete=models.CASCADE,
        related_name="purposes",
    )
    payment_type_config = models.ForeignKey(
        RequestApprovalPaymentTypeConfig,
        on_delete=models.CASCADE,
        related_name="purpose_exception_purpose_links",
    )
    payment_purpose = models.ForeignKey(
        RequestPaymentPurposeConfig,
        on_delete=models.CASCADE,
        related_name="approval_purpose_exceptions",
    )

    class Meta:
        db_table = "request_approval_purpose_exception_purposes"
        constraints = [
            models.UniqueConstraint(
                fields=["exception_config", "payment_purpose"],
                name="req_appr_exc_purpose_uniq",
            ),
            models.UniqueConstraint(
                fields=["payment_type_config", "payment_purpose"],
                name="req_appr_exc_pt_purpose_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["exception_config"], name="req_appr_exc_purpose_exc_idx"),
            models.Index(fields=["payment_type_config"], name="req_appr_exc_purpose_pt_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.exception_config_id and not self.payment_type_config_id:
            self.payment_type_config_id = self.exception_config.payment_type_config_id
        return super().save(*args, **kwargs)


class RequestApprovalPurposeExceptionStepConfig(models.Model):
    exception_config = models.ForeignKey(
        RequestApprovalPurposeExceptionConfig,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    step = models.IntegerField()
    step_type = models.CharField(max_length=16, choices=Approval.STEP_TYPE_CHOICES, default=Approval.STEP_TYPE_SERIAL)
    is_enabled = models.BooleanField(default=True)
    payment_action_mode = models.CharField(
        max_length=12,
        choices=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CHOICES,
        default=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK,
    )
    payment_webapp_url = models.TextField(blank=True, default="")
    telegram_chat = models.ForeignKey(
        "telegram_approvals.TenantTelegramChat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_purpose_exception_steps",
    )

    class Meta:
        db_table = "request_approval_purpose_exception_step_configs"
        constraints = [
            models.UniqueConstraint(
                fields=["exception_config", "step"],
                name="req_appr_exc_step_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["exception_config", "step"], name="req_appr_exc_step_idx"),
            models.Index(fields=["exception_config"], name="req_appr_exc_steps_exc_idx"),
        ]


class RequestApprovalPurposeExceptionStepApproverConfig(models.Model):
    step_config = models.ForeignKey(
        RequestApprovalPurposeExceptionStepConfig,
        on_delete=models.CASCADE,
        related_name="approvers",
    )
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="request_approval_purpose_exception_step_approver_configs",
    )

    class Meta:
        db_table = "request_approval_purpose_exception_step_approver_configs"
        constraints = [
            models.UniqueConstraint(
                fields=["step_config", "approver_user"],
                name="req_appr_exc_step_approver_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["step_config"], name="req_appr_exc_step_appr_idx"),
        ]


class UserRequestApproval(models.Model):
    """
    Inbox model for current approver.

    Implementation detail:
    - It maps to the same DB table as `Approval` (`db_table="approvals"`),
      so there is no duplicated projection table.
    """

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="user_request_approvals")
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="user_request_approvals",
    )
    approver_recipient_id = models.BigIntegerField(null=True, blank=True)
    approver_external_user_id = models.BigIntegerField(null=True, blank=True)
    telegram_message = models.OneToOneField(
        "telegram_approvals.TelegramMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="user_request_approval",
    )
    step = models.IntegerField(default=1)
    step_type = models.CharField(max_length=16, default=Approval.STEP_TYPE_SERIAL, choices=Approval.STEP_TYPE_CHOICES)
    decision = models.CharField(max_length=12, default=Approval.DECISION_PENDING, choices=Approval.DECISION_CHOICES)
    resend_batch_id = models.UUIDField(default=uuid.uuid4, editable=False)
    resend_key = models.CharField(max_length=128, null=True, blank=True)
    replaced_approval = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="user_resend_children"
    )
    comment = models.TextField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    # --- Derived read-only accessors (mirrors Approval) ---
    @property
    def gateway_message_id(self):
        tm = self.telegram_message
        return tm.message_id if tm else None

    @property
    def message_sent(self) -> bool:
        return self.telegram_message_id is not None

    @property
    def message_sent_at(self):
        tm = self.telegram_message
        return tm.sent_at if tm else None

    class Meta:
        db_table = "approvals"
        managed = False


class AutoRequestTemplate(models.Model):
    """Месяц начисления в заявке относительно календарного месяца дня запуска шаблона."""

    BILLING_MONTH_PREVIOUS = "previous"
    BILLING_MONTH_CURRENT = "current"
    BILLING_MONTH_NEXT = "next"
    BILLING_MONTH_MODE_CHOICES = [
        (BILLING_MONTH_PREVIOUS, "Предыдущий месяц"),
        (BILLING_MONTH_CURRENT, "Этот месяц"),
        (BILLING_MONTH_NEXT, "Следующий месяц"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="auto_request_templates")
    is_enabled = models.BooleanField(default=False)
    name = models.CharField(max_length=150, default="")
    payment_type = models.CharField(max_length=50, choices=Request.PAYMENT_TYPE_CHOICES)
    day_of_month = models.IntegerField(default=1)
    billing_month_mode = models.CharField(
        max_length=20,
        choices=BILLING_MONTH_MODE_CHOICES,
        default=BILLING_MONTH_CURRENT,
    )

    title_template = models.CharField(max_length=200, default="")
    description_template = models.TextField(default="")

    company_payer = models.CharField(max_length=100, default="", blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default=Request.CURRENCY_UZS, choices=Request.CURRENCY_CHOICES)
    urgency = models.CharField(max_length=50, default=Request.URGENCY_NORMAL, choices=Request.URGENCY_CHOICES)
    payment_purpose = models.CharField(max_length=200, default="", blank=True)
    vendor_ref = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auto_request_templates",
    )
    contract_ref = models.ForeignKey(
        "contracts.Contract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auto_request_templates",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="auto_request_templates",
    )

    # First day of month (YYYY-MM-01) of latest successful run.
    last_run_month = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_auto_request_templates",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "auto_request_templates"
        indexes = [
            models.Index(fields=["tenant", "is_enabled"], name="auto_req_tenant_enabled_idx"),
            models.Index(fields=["tenant", "payment_type"], name="auto_req_tenant_payment_idx"),
            models.Index(fields=["tenant", "last_run_month"], name="auto_req_tenant_run_month_idx"),
        ]


class RequestComment(models.Model):
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="comments")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="request_comments",
    )
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "request_comments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["request", "created_at"], name="reqcomments_req_created_idx"),
        ]
