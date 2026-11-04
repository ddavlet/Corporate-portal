"""Standard Telegram mini-app links for a tenant bot and the BotFather setup checklist.

Telegram has no Bot API for Main App / Direct Links, so the portal only builds the
expected values from the tenant's bot username and shows them to the owner.
"""

from __future__ import annotations

from apps.modules.requests.telegram_webapp_links import tenant_bot_username
from apps.modules.telegram_approvals.bot_profile import mini_app_url

PAYMENT_APP_SHORT_NAME = "payment"
PORTAL_APP_SHORT_NAME = "portal"


def direct_link(tenant, short_name: str) -> str:
    username = tenant_bot_username(tenant)
    if not username:
        return ""
    return f"https://t.me/{username}/{short_name}"


def default_payment_webapp_url(tenant) -> str:
    return direct_link(tenant, PAYMENT_APP_SHORT_NAME)


def bot_setup_checklist(tenant) -> dict:
    # Lazy: services imports formatter, which imports this module.
    from apps.modules.telegram_approvals.services import get_tenant_bot_token

    main_app_url = mini_app_url(tenant) or ""
    return {
        "bot_username": tenant_bot_username(tenant),
        "has_bot_token": bool(get_tenant_bot_token(tenant)),
        "main_app_url": main_app_url,
        "launch_mode": "fullscreen",
        "direct_links": [
            {
                "short_name": PAYMENT_APP_SHORT_NAME,
                "web_app_url": f"{main_app_url}payment" if main_app_url else "",
                "link": direct_link(tenant, PAYMENT_APP_SHORT_NAME),
            },
            {
                "short_name": PORTAL_APP_SHORT_NAME,
                "web_app_url": main_app_url,
                "link": direct_link(tenant, PORTAL_APP_SHORT_NAME),
            },
        ],
        "auto_synced": ["commands", "description", "menu_button"],
    }
