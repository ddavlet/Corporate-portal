from __future__ import annotations

from django.db import transaction

from apps.modules.cash_desk.models import CashDeskConfig
from apps.modules.telegram_approvals.models import TenantTelegramChat


def get_active_config(tenant) -> CashDeskConfig | None:
    return CashDeskConfig.objects.filter(tenant=tenant, is_active=True).select_related("telegram_chat").first()


def config_payload(tenant) -> dict:
    config = CashDeskConfig.objects.filter(tenant=tenant).first()
    chats = TenantTelegramChat.objects.filter(tenant=tenant, is_active=True).order_by("name")
    return {
        "is_active": bool(config and config.is_active),
        "telegram_chat_id": config.telegram_chat_id if config else None,
        "options": {"telegram_chats": [{"id": c.id, "name": c.name} for c in chats]},
    }


def save_config(*, tenant, data: dict, actor) -> None:
    with transaction.atomic():
        config, _ = CashDeskConfig.objects.select_for_update().get_or_create(tenant=tenant)
        config.is_active = data["is_active"]
        config.telegram_chat_id = data.get("telegram_chat_id")
        config.updated_by = actor
        config.save()
