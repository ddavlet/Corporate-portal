from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class PortalFeedback(models.Model):
    KIND_ERROR = "error"
    KIND_IMPROVEMENT = "improvement"
    KIND_CHOICES = [
        (KIND_ERROR, KIND_ERROR),
        (KIND_IMPROVEMENT, KIND_IMPROVEMENT),
    ]

    DELIVERY_PENDING = "pending"
    DELIVERY_SENT = "sent"
    DELIVERY_FAILED = "failed"
    DELIVERY_SKIPPED = "skipped"
    DELIVERY_STATUS_CHOICES = [
        (DELIVERY_PENDING, DELIVERY_PENDING),
        (DELIVERY_SENT, DELIVERY_SENT),
        (DELIVERY_FAILED, DELIVERY_FAILED),
        (DELIVERY_SKIPPED, DELIVERY_SKIPPED),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="portal_feedbacks")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="portal_feedbacks",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    body = models.TextField()
    page_path = models.CharField(max_length=500, blank=True, default="")

    delivery_status = models.CharField(
        max_length=10,
        choices=DELIVERY_STATUS_CHOICES,
        default=DELIVERY_PENDING,
    )
    delivery_error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "portal_feedbacks"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "created_at"], name="portal_fb_tenant_created_idx"),
        ]
