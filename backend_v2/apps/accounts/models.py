from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class User(AbstractUser):
    # Separate from `username`; used as a human-readable display name.
    full_name = models.CharField(max_length=255, blank=True, default="")
    telegram_chat_id = models.BigIntegerField(null=True, blank=True)
    telegram_from_id = models.BigIntegerField(null=True, blank=True)

    class Meta(AbstractUser.Meta):
        verbose_name = "user"
        verbose_name_plural = "users"


class OtpChallenge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otp_challenges")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="otp_challenges")
    code_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    attempts = models.IntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "user", "created_at"], name="otp_tenant_user_created_idx"),
            models.Index(fields=["expires_at"], name="otp_challenge_expires_idx"),
        ]

