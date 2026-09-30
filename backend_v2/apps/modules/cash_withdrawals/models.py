from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class CashWithdrawalConfig(models.Model):
    """Per-tenant settings: which PAYED requests await a cash receipt, who confirms, who gets alerts."""

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="cash_withdrawal_config")
    is_active = models.BooleanField(default=False)
    card_telegram_chat = models.ForeignKey(
        "telegram_approvals.TenantTelegramChat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_withdrawal_card_configs",
    )
    alert_telegram_chat = models.ForeignKey(
        "telegram_approvals.TenantTelegramChat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_withdrawal_alert_configs",
    )
    alert_after_days = models.PositiveIntegerField(default=3, validators=[MinValueValidator(1)])
    alert_repeat_every_days = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    alert_hour = models.PositiveSmallIntegerField(
        default=9,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text="Hour of day (0–23, Asia/Tashkent) when overdue alerts are dispatched.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="updated_cash_withdrawal_configs",
    )

    class Meta:
        db_table = "cash_withdrawal_configs"

    def __str__(self):
        return f"CashWithdrawalConfig(tenant={self.tenant_id}, active={self.is_active})"


class CashWithdrawalConfirmer(models.Model):
    config = models.ForeignKey(CashWithdrawalConfig, on_delete=models.CASCADE, related_name="confirmers", db_index=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_withdrawal_confirmer_rows"
    )

    class Meta:
        db_table = "cash_withdrawal_confirmers"
        constraints = [models.UniqueConstraint(fields=["config", "user"], name="cw_confirmer_uniq")]


class CashWithdrawalAlertRecipient(models.Model):
    config = models.ForeignKey(
        CashWithdrawalConfig, on_delete=models.CASCADE, related_name="alert_recipients", db_index=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_withdrawal_alert_rows"
    )

    class Meta:
        db_table = "cash_withdrawal_alert_recipients"
        constraints = [models.UniqueConstraint(fields=["config", "user"], name="cw_alert_recipient_uniq")]


class CashWithdrawalRule(models.Model):
    """PAYED request with this (payment_type, payment_purpose) awaits a cash receipt into `wallet`."""

    config = models.ForeignKey(CashWithdrawalConfig, on_delete=models.CASCADE, related_name="rules", db_index=False)
    payment_type = models.CharField(max_length=50)
    payment_purpose = models.CharField(max_length=200)
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.PROTECT, related_name="cash_withdrawal_rules")

    class Meta:
        db_table = "cash_withdrawal_rules"
        constraints = [
            models.UniqueConstraint(fields=["config", "payment_type", "payment_purpose"], name="cw_rule_uniq")
        ]


class CashWithdrawalReceipt(models.Model):
    """One expected cash receipt per PAYED withdrawal request."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        CONFIRMED = "confirmed", "Подтверждено"
        CLOSED = "closed", "Закрыто без дохода"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cash_withdrawal_receipts", db_index=False)
    request = models.OneToOneField(
        "requests.Request", on_delete=models.PROTECT, related_name="cash_withdrawal_receipt"
    )
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.PROTECT, related_name="cash_withdrawal_receipts")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=10)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="confirmed_cash_withdrawal_receipts",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cash_revenue = models.OneToOneField(
        "cashier.CashRevenue",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cash_withdrawal_receipt",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_cash_withdrawal_receipts",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_comment = models.TextField(blank=True, default="")
    last_alert_at = models.DateTimeField(null=True, blank=True)
    alert_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "cash_withdrawal_receipts"
        indexes = [models.Index(fields=["tenant", "status", "created_at"], name="cw_receipt_tnt_status_idx")]

    def __str__(self):
        return f"CashWithdrawalReceipt(id={self.pk}, request={self.request_id}, status={self.status})"


class CashWithdrawalMessage(models.Model):
    """Telegram message sent for a receipt (card with the button, or an overdue alert)."""

    class Kind(models.TextChoices):
        CARD = "card", "Карточка"
        ALERT = "alert", "Предупреждение"

    receipt = models.ForeignKey(CashWithdrawalReceipt, on_delete=models.CASCADE, related_name="messages", db_index=False)
    telegram_message = models.OneToOneField(
        "telegram_approvals.TelegramMessage", on_delete=models.CASCADE, related_name="cash_withdrawal_message"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cash_withdrawal_messages"
        indexes = [models.Index(fields=["receipt", "kind"], name="cw_message_receipt_kind_idx")]
