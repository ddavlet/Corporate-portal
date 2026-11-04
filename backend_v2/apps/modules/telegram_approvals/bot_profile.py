"""Push the tenant bot's profile (command menu, descriptions, menu button) to Telegram.

Runs through tg-gateway. Each of the three calls is independent: a failure is
logged and does not stop the others. Used on bot-token save and by the
`sync_telegram_bots` management command (run on every deploy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MENU_BUTTON_TEXT = "Портал"
BASE_DESCRIPTION = (
    "Бот портала Kolberg: согласования, уведомления и остатки. "
    "Остатки по банку, кассе и картам — командами из меню."
)
ASSISTANT_DESCRIPTION_SUFFIX = " Также можно просто написать вопрос по заявкам, отчётам и инвестициям — бот ответит."
SHORT_DESCRIPTION = "Согласования, уведомления и остатки компании."
ASSISTANT_SHORT_DESCRIPTION = "Согласования, остатки и ответы на вопросы по финансам компании."
REQUEST_TIMEOUT = 12


@dataclass
class BotProfileSyncResult:
    tenant_id: int
    commands_ok: bool
    description_ok: bool
    menu_button_ok: bool | None  # None = skipped (no usable BASE_DOMAIN)


def _assistant_enabled(tenant) -> bool:
    try:
        from apps.modules.ai_assistant.access import assistant_enabled
    except ImportError:
        logger.warning("ai_assistant module unavailable; bot description without assistant text")
        return False
    return bool(assistant_enabled(tenant))


def build_descriptions(tenant) -> tuple[str, str]:
    if _assistant_enabled(tenant):
        return BASE_DESCRIPTION + ASSISTANT_DESCRIPTION_SUFFIX, ASSISTANT_SHORT_DESCRIPTION
    return BASE_DESCRIPTION, SHORT_DESCRIPTION


def mini_app_url(tenant) -> str | None:
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lstrip(".")
    if not base_domain or base_domain in ("localhost", "127.0.0.1"):
        return None
    return f"https://{tenant.subdomain}.{base_domain}/app/tg/"


def _post(tenant, path: str, payload: dict) -> tuple[bool, str]:
    """POST to the gateway; returns (ok, human-readable failure reason)."""
    from apps.tenants.views import _gateway_base_url

    try:
        resp = requests.post(f"{_gateway_base_url()}{path}", json=payload, timeout=REQUEST_TIMEOUT)
        data = resp.json() if resp.content else {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Telegram bot profile %s failed tenant=%s: %s", path, tenant.pk, type(exc).__name__)
        return False, type(exc).__name__
    if resp.status_code >= 400 or not data.get("ok"):
        reason = (
            (data.get("telegram") or {}).get("description")
            or (data.get("short_telegram") or {}).get("description")
            or f"status {resp.status_code}"
        )
        logger.warning("Telegram bot profile %s failed tenant=%s status=%s description=%s", path, tenant.pk, resp.status_code, reason)
        return False, str(reason)
    return True, ""


def sync_bot_profile(tenant) -> BotProfileSyncResult | None:
    from apps.modules.telegram_approvals.command_handlers import WALLET_BALANCE_COMMANDS

    bot_token = tenant.get_telegram_bot_token()
    if not bot_token:
        return None

    commands = [{"command": spec.command, "description": spec.title} for spec in WALLET_BALANCE_COMMANDS.values()]
    commands_ok, _ = _post(tenant, "/v1/messaging/commands/set", {"bot_token": bot_token, "commands": commands})

    description, short_description = build_descriptions(tenant)
    description_ok, _ = _post(
        tenant,
        "/v1/messaging/description/set",
        {"bot_token": bot_token, "description": description, "short_description": short_description},
    )

    url = mini_app_url(tenant)
    if url is None:
        logger.warning("BASE_DOMAIN is empty or localhost; skipping menu button tenant=%s", tenant.pk)
        menu_button_ok = None
    else:
        menu_button_ok, _ = _post(
            tenant,
            "/v1/messaging/menu-button/set",
            {"bot_token": bot_token, "text": MENU_BUTTON_TEXT, "url": url},
        )

    return BotProfileSyncResult(
        tenant_id=tenant.pk,
        commands_ok=commands_ok,
        description_ok=description_ok,
        menu_button_ok=menu_button_ok,
    )
