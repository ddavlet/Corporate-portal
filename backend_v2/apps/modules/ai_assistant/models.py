from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class ChainNode(models.Model):
    """Message in a Telegram reply chain (user question, other member, bot answer)."""

    KIND_USER = "user"
    KIND_MEMBER = "member"
    KIND_BOT_AGENT = "bot_agent"
    KIND_BOT_AUTO = "bot_auto"
    KIND_CHOICES = [
        (KIND_USER, "Спрашивающий (допущенный)"),
        (KIND_MEMBER, "Другой участник цепочки"),
        (KIND_BOT_AGENT, "Ответ агента"),
        (KIND_BOT_AUTO, "Автосообщение бота"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="ai_chain_nodes", db_index=False)
    chat_id = models.CharField(max_length=50)
    message_id = models.BigIntegerField()
    parent_message_id = models.BigIntegerField(null=True, blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_chain_nodes",
    )
    author_tg_id = models.BigIntegerField(null=True, blank=True)
    author_label = models.CharField(max_length=255, blank=True, default="")
    author_roles = models.CharField(max_length=100, blank=True, default="")
    text = models.TextField(blank=True, default="")
    agent_messages = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "chat_id", "message_id"], name="aia_node_tenant_chat_msg_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "chat_id", "parent_message_id"], name="aia_node_parent_idx"),
            models.Index(fields=["created_at"], name="aia_node_created_idx"),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.chat_id}:{self.message_id} ({self.kind})"


class PendingConfirmation(models.Model):
    """Write tool calls proposed by the agent, waiting for a button confirmation."""

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Ожидает"),
        (STATUS_CONFIRMED, "Подтверждено"),
        (STATUS_CANCELLED, "Отменено"),
        (STATUS_EXPIRED, "Истекло"),
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="ai_pending_confirmations", db_index=False
    )
    chat_id = models.CharField(max_length=50)
    requester_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_pending_confirmations"
    )
    requester_tg_id = models.BigIntegerField()
    origin_message_id = models.BigIntegerField()
    confirmation_message = models.ForeignKey(
        "telegram_approvals.TelegramMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_pending_confirmations",
    )
    agent_messages = models.JSONField()
    tool_calls = models.JSONField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "status"], name="aia_pending_tenant_status_idx"),
        ]

    def __str__(self):
        return f"Confirmation {self.pk} ({self.status})"


class UsageRecord(models.Model):
    """One agent run: tokens, cost, MCP calls."""

    OUTCOME_ANSWERED = "answered"
    OUTCOME_CONFIRMATION_REQUESTED = "confirmation_requested"
    OUTCOME_REFUSED = "refused"
    OUTCOME_ERROR = "error"
    OUTCOME_CHOICES = [
        (OUTCOME_ANSWERED, "Ответ"),
        (OUTCOME_CONFIRMATION_REQUESTED, "Запрошено подтверждение"),
        (OUTCOME_REFUSED, "Отказ"),
        (OUTCOME_ERROR, "Ошибка"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="ai_usage_records", db_index=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_records",
    )
    chat_id = models.CharField(max_length=50)
    created_at = models.DateTimeField(default=timezone.now)
    model = models.CharField(max_length=64)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_creation_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    mcp_calls = models.PositiveSmallIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=30, choices=OUTCOME_CHOICES)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "created_at"], name="aia_usage_tenant_created_idx"),
        ]

    def __str__(self):
        return f"Usage {self.pk} {self.model} ${self.cost_usd}"
