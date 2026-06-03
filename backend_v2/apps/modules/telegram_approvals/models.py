from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.tenants.models import Tenant


class TelegramMessage(models.Model):
    """Sent Telegram message linked to a document in any module (task, approval, note, etc.)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="telegram_messages")
    recipient_id = models.CharField(max_length=50)
    external_user_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField()
    sent_at = models.DateTimeField()

    # Resend tracking: mutated in-place when the card is re-sent.
    resend_count = models.PositiveSmallIntegerField(default=0)
    last_resend_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "telegram_messages"
        indexes = [
            models.Index(fields=["tenant", "recipient_id"], name="tgmsg_tenant_recipient_idx"),
            models.Index(fields=["message_id"], name="tgmsg_message_id_idx"),
        ]

    def __str__(self):
        return f"TelegramMessage(id={self.pk}, message_id={self.message_id}, recipient={self.recipient_id})"


class TelegramMessageHistory(models.Model):
    """
    Immutable audit log of every gateway action taken on a TelegramMessage.

    One row per action: send, edit, deactivate, resend_old (deactivation of old card during
    resend), resend_new (new card sent during resend), callback (Telegram button press),
    delete. Records the exact payload sent to the gateway and the response received, with
    bot_token redacted so the table is safe for developer inspection.
    """

    ACTION_SEND = "send"
    ACTION_EDIT = "edit"
    ACTION_DEACTIVATE = "deactivate"
    ACTION_RESEND_OLD = "resend_old"
    ACTION_RESEND_NEW = "resend_new"
    ACTION_CALLBACK = "callback"
    ACTION_DELETE = "delete"
    ACTION_CHOICES = [
        (ACTION_SEND, "Send (initial dispatch)"),
        (ACTION_EDIT, "Edit (card updated)"),
        (ACTION_DEACTIVATE, "Deactivate (buttons removed)"),
        (ACTION_RESEND_OLD, "Resend — old card deactivated"),
        (ACTION_RESEND_NEW, "Resend — new card sent"),
        (ACTION_CALLBACK, "Callback (button pressed in Telegram)"),
        (ACTION_DELETE, "Delete"),
    ]

    telegram_message = models.ForeignKey(
        TelegramMessage,
        on_delete=models.CASCADE,
        related_name="history",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)

    # Telegram message_id at the moment of this action (old id for resend_old, new id for resend_new).
    message_id = models.BigIntegerField(null=True, blank=True)
    recipient_id = models.CharField(max_length=50, blank=True)
    external_user_id = models.BigIntegerField(null=True, blank=True)

    # Rendered content snapshot.
    text = models.TextField(blank=True)
    buttons = models.JSONField(null=True, blank=True)

    # Gateway round-trip — bot_token is always redacted before storage.
    request_payload = models.JSONField(null=True, blank=True)
    response_payload = models.JSONField(null=True, blank=True)

    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)

    # Who triggered this action.
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="telegram_message_history_actions",
    )
    actor_external_user_id = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "telegram_message_history"
        indexes = [
            models.Index(fields=["telegram_message", "created_at"], name="tgmsghistory_msg_created_idx"),
            models.Index(fields=["message_id"], name="tgmsghistory_message_id_idx"),
            models.Index(fields=["action"], name="tgmsghistory_action_idx"),
        ]
        ordering = ["created_at"]

    def __str__(self):
        return f"TelegramMessageHistory(id={self.pk}, action={self.action}, message_id={self.message_id})"


class Notification(models.Model):
    """Outbound notification that was sent via Telegram (drafts, portal feedback, etc.).

    Unlike Approval/Task links (OneToOne to TelegramMessage), notifications use a
    GenericForeignKey so the same model can reference Request, PortalFeedback, or any
    future source object. This makes every dispatched Telegram message traceable in
    the TelegramMessages table for debugging.
    """

    KIND_DRAFT = "draft"
    KIND_PORTAL_FEEDBACK = "portal_feedback"
    KIND_NOTE = "note"
    KIND_CHOICES = [
        (KIND_DRAFT, "Draft request notification"),
        (KIND_PORTAL_FEEDBACK, "Portal feedback delivery"),
        (KIND_NOTE, "Note delivery"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    telegram_message = models.OneToOneField(
        TelegramMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notification",
    )

    # Generic reference to the source object (Request, PortalFeedback, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    source_object = GenericForeignKey("content_type", "object_id")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        indexes = [
            models.Index(fields=["tenant", "kind", "created_at"], name="notif_tenant_kind_created_idx"),
            models.Index(fields=["content_type", "object_id"], name="notif_source_idx"),
        ]

    def __str__(self):
        return f"Notification(id={self.pk}, kind={self.kind}, source={self.content_type}:{self.object_id})"


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
