"""Read/write of CardTopupNotifyConfig for the settings API."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.modules.cash_desk.models import CardTopupNotifyConfig
from apps.tenants.models import TenantMembership

User = get_user_model()


def _user_name(user) -> str:
    return (getattr(user, "full_name", "") or "").strip() or user.username


def available_users(tenant):
    member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
    return User.objects.filter(id__in=member_ids, is_active=True).order_by("full_name", "username", "id")


def card_topup_config_payload(tenant) -> dict:
    config = CardTopupNotifyConfig.objects.filter(tenant=tenant).first()
    users = list(available_users(tenant))
    member_ids = {u.id for u in users}
    recipient_ids = (
        sorted(uid for uid in config.recipients.values_list("id", flat=True) if uid in member_ids) if config else []
    )
    return {
        "is_active": bool(config and config.is_active),
        "recipient_ids": recipient_ids,
        "available_users": [
            {"id": u.id, "name": _user_name(u), "has_telegram": bool(u.telegram_chat_id)} for u in users
        ],
    }


def save_card_topup_config(*, tenant, data: dict, actor) -> None:
    with transaction.atomic():
        config, _ = CardTopupNotifyConfig.objects.select_for_update().get_or_create(tenant=tenant)
        config.is_active = data["is_active"]
        config.updated_by = actor
        config.save()
        config.recipients.set(data["recipient_ids"])
