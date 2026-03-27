from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class Note(models.Model):
    TARGET_REQUEST = "request"
    TARGET_CASH = "cash"
    TARGET_BANK = "bank"
    TARGET_TYPE_CHOICES = [
        (TARGET_REQUEST, TARGET_REQUEST),
        (TARGET_CASH, TARGET_CASH),
        (TARGET_BANK, TARGET_BANK),
    ]

    DELIVERY_PENDING = "pending"
    DELIVERY_SENT = "sent"
    DELIVERY_FAILED = "failed"
    DELIVERY_STATUS_CHOICES = [
        (DELIVERY_PENDING, DELIVERY_PENDING),
        (DELIVERY_SENT, DELIVERY_SENT),
        (DELIVERY_FAILED, DELIVERY_FAILED),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="notes")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_notes",
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_notes",
    )

    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    target_id = models.BigIntegerField()
    message = models.TextField()

    delivery_status = models.CharField(
        max_length=10,
        choices=DELIVERY_STATUS_CHOICES,
        default=DELIVERY_PENDING,
    )
    delivery_error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "notes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "target_type", "target_id"], name="notes_tenant_target_idx"),
            models.Index(fields=["recipient_user", "created_at"], name="notes_recipient_created_idx"),
        ]
