from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # Separate from `username`; used as a human-readable display name.
    full_name = models.CharField(max_length=255, blank=True, default="")
    telegram_chat_id = models.BigIntegerField(null=True, blank=True)
    telegram_from_id = models.BigIntegerField(null=True, blank=True)

    class Meta(AbstractUser.Meta):
        verbose_name = "user"
        verbose_name_plural = "users"

