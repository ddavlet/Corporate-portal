"""
Direct Link Mini App (t.me/<bot>/<app>) helpers for the request approval config.

A t.me link opens the Mini App only inside the bot it names, so the link must point
at the tenant's own bot (Tenant.telegram_bot_username).
"""

from urllib.parse import urlsplit

TME_HOSTS = ("t.me", "www.t.me", "telegram.me", "www.telegram.me")


def normalize_tme_url(url: str) -> str:
    """Add https:// to a scheme-less t.me link — Telegram rejects url buttons without a scheme."""
    u = (url or "").strip()
    if not u or "://" in u:
        return u
    if u.lower().split("/", 1)[0] in TME_HOSTS:
        return f"https://{u}"
    return u


def tme_bot_username(url: str) -> str | None:
    """Bot username from a t.me link ("" when the path is empty), None for non-t.me URLs."""
    parts = urlsplit((url or "").strip())
    if (parts.hostname or "").lower() not in TME_HOSTS:
        return None
    return parts.path.strip("/").split("/", 1)[0].lstrip("@")


def tenant_bot_username(tenant) -> str:
    return (getattr(tenant, "telegram_bot_username", "") or "").strip().lstrip("@")


def tenant_bot_mismatch_error(*, url: str, tenant) -> str | None:
    """Error text when a t.me link points at a bot other than the tenant's; None if it is fine or unknown."""
    link_bot = tme_bot_username(url)
    if link_bot is None:
        return None
    tenant_bot = tenant_bot_username(tenant)
    if not tenant_bot:
        return None
    if not link_bot:
        return f"Укажите бота в ссылке: https://t.me/{tenant_bot}/ИмяПриложения"
    if link_bot.lower() != tenant_bot.lower():
        return (
            f"Ссылка ведёт на бота @{link_bot}, а бот тенанта — @{tenant_bot}. "
            f"Mini App откроется только в своём боте: https://t.me/{tenant_bot}/ИмяПриложения"
        )
    return None
