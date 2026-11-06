from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class CashDeskConfig(models.Model):
    """Per-tenant settings: whether cash-desk notifications are on and which Telegram group receives them."""

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="cash_desk_config")
    is_active = models.BooleanField(default=False)
    telegram_chat = models.ForeignKey(
        "telegram_approvals.TenantTelegramChat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_desk_configs",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="updated_cash_desk_configs",
    )

    class Meta:
        db_table = "cash_desk_configs"

    def __str__(self):
        return f"CashDeskConfig(tenant={self.tenant_id}, active={self.is_active})"


class CashRegisterTransferTarget(models.Model):
    """Destination register/amount of a cash-to-cash transfer request (set when the request is created)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cash_register_transfer_targets", db_index=False)
    request = models.OneToOneField("requests.Request", on_delete=models.CASCADE, related_name="cash_transfer_target")
    to_wallet = models.ForeignKey("wallets.Wallet", on_delete=models.PROTECT, related_name="cash_transfer_targets")
    to_amount = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cash_register_transfer_targets"

    def __str__(self):
        return f"CashRegisterTransferTarget(request={self.request_id}, to_wallet={self.to_wallet_id})"


class CashDeskMessage(models.Model):
    """Notification attempt for a PAYED cash request; one row per request makes the handler idempotent."""

    class Kind(models.TextChoices):
        TRANSFER = "transfer", "Перевод между кассами"
        EXPENSE = "expense", "Расход"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка"
        SKIPPED = "skipped", "Пропущено"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cash_desk_messages", db_index=False)
    request = models.OneToOneField("requests.Request", on_delete=models.CASCADE, related_name="cash_desk_message")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    telegram_message = models.OneToOneField(
        "telegram_approvals.TelegramMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_desk_message",
    )
    error = models.TextField(blank=True, default="")
    revenue_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cash_desk_messages"

    def __str__(self):
        return f"CashDeskMessage(request={self.request_id}, kind={self.kind}, status={self.status})"
