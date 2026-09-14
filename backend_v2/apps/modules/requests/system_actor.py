"""Shared system-actor account used to attribute audit comments left by
one-off data-fix management commands (not a real human operator).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

SYSTEM_USERNAME = "system"
SYSTEM_FULL_NAME = "Система"


def get_or_create_system_user():
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=SYSTEM_USERNAME,
        defaults={"full_name": SYSTEM_FULL_NAME, "is_active": False},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    elif user.full_name != SYSTEM_FULL_NAME:
        user.full_name = SYSTEM_FULL_NAME
        user.save(update_fields=["full_name"])
    return user
