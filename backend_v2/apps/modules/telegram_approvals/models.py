from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class TelegramMessage(models.Model):
    """Sent Telegram message linked to a document in any module (task, approval, note, etc.)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="telegram_messages")
    recipient_id = models.CharField(max_length=50)
    external_user_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField()
    sent_at = models.DateTimeField()

    class Meta:
        db_table = "telegram_messages"
        indexes = [
            models.Index(fields=["tenant", "recipient_id"], name="tgmsg_tenant_recipient_idx"),
            models.Index(fields=["message_id"], name="tgmsg_message_id_idx"),
        ]

    def __str__(self):
        return f"TelegramMessage(id={self.pk}, message_id={self.message_id}, recipient={self.recipient_id})"


class TenantTelegramChat(models.Model):
    """Telegram group chat registered for a tenant. Used as a shared destination for notifications and approvals."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="telegram_chats")
    name = models.CharField(max_length=100)
    chat_id = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    # nullable to allow auto-migrated entries that have no known creator
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_telegram_chats",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_edit_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenant_telegram_chats"
        unique_together = [("tenant", "chat_id")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.chat_id})"
