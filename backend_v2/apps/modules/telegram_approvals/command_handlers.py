"""Telegram slash-command handlers (balances and future commands).

Gateway forwards ``event=command``; this module resolves tenant/user, checks
module ACL, and replies in the same chat (private or group).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import balances_for_tenant_channel
from apps.tenants.models import Tenant
from apps.tenants.permissions import has_effective_module_access

logger = logging.getLogger(__name__)
User = get_user_model()

ACCESS_DENIED_TEXT = "Нет доступа к этой команде."


@dataclass(frozen=True)
class WalletBalanceCommandSpec:
    command: str
    module_key: str
    wallet_type: str
    title: str


WALLET_BALANCE_COMMANDS: dict[str, WalletBalanceCommandSpec] = {
    "bank_ostatki": WalletBalanceCommandSpec(
        command="bank_ostatki",
        module_key="bank",
        wallet_type=Wallet.Type.BANK,
        title="Банк — остатки",
    ),
    "cash_ostatki": WalletBalanceCommandSpec(
        command="cash_ostatki",
        module_key="cash",
        wallet_type=Wallet.Type.CASH,
        title="Касса — остатки",
    ),
    "card_ostatki": WalletBalanceCommandSpec(
        command="card_ostatki",
        module_key="corporate_card",
        wallet_type=Wallet.Type.CORPORATE_CARD,
        title="Корп. карта — остатки",
    ),
}


def format_money_amount(amount: str | Decimal, currency: str) -> str:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        value = Decimal("0")
    formatted = f"{value:,.2f}".replace(",", " ")
    cur = (currency or "").strip()
    return f"{formatted} {cur}".strip() if cur else formatted


def format_wallet_balances_message(*, title: str, rows: list[dict]) -> str:
    if not rows:
        return f"{title}\nНет данных."
    lines = [title]
    for row in rows:
        name = (row.get("display_name") or "").strip() or "Счёт"
        amount = format_money_amount(row.get("current_balance") or "0", row.get("currency") or "")
        lines.append(f"• {name}: {amount}")
    return "\n".join(lines)


def resolve_tenant_by_bot_id(bot_id: str | None) -> Tenant | None:
    """Match tenant by Telegram bot id (token prefix before ':'), never the secret."""
    needle = str(bot_id or "").strip()
    if not needle:
        return None
    for tenant in Tenant.objects.exclude(telegram_bot_token_enc="").iterator():
        token = (tenant.get_telegram_bot_token() or "").strip()
        if not token:
            continue
        if token.split(":", 1)[0] == needle:
            return tenant
    return None


def resolve_user_by_telegram_id(telegram_user_id: str | int | None):
    raw = str(telegram_user_id or "").strip()
    if not raw:
        return None
    try:
        tg_id = int(raw)
    except (TypeError, ValueError):
        return None
    return (
        User.objects.filter(Q(telegram_from_id=tg_id) | Q(telegram_chat_id=tg_id))
        .order_by("id")
        .first()
    )


def _reply(*, tenant: Tenant, recipient_id: str, text: str, external_user_id: int | None) -> None:
    TelegramDispatcher(tenant).send(
        action="send",
        recipient_id=str(recipient_id),
        text=text,
        buttons=None,
        external_user_id=external_user_id,
    )


def handle_wallet_balance_command(
    *,
    spec: WalletBalanceCommandSpec,
    tenant: Tenant,
    user,
    recipient_id: str,
    telegram_user_id: int | None,
) -> str:
    """Return the message that was (or would be) sent."""
    if user is None or not has_effective_module_access(
        user=user, tenant=tenant, module_key=spec.module_key
    ):
        text = ACCESS_DENIED_TEXT
    else:
        rows = balances_for_tenant_channel(tenant_id=tenant.id, wallet_type=spec.wallet_type)
        text = format_wallet_balances_message(title=spec.title, rows=rows)
    _reply(
        tenant=tenant,
        recipient_id=recipient_id,
        text=text,
        external_user_id=telegram_user_id,
    )
    return text


def handle_telegram_command(
    *,
    command: str,
    bot_id: str | None,
    user_id: str | None,
    recipient_id: str | None,
) -> dict:
    """
    Dispatch a slash command from the messaging gateway.

    Unknown commands are ignored (202). Missing tenant/bot mapping is logged and ignored
    (cannot reply without a bot). Access failures still reply with ACCESS_DENIED_TEXT.
    """
    cmd = (command or "").strip().lstrip("/").lower()
    chat_id = str(recipient_id or "").strip()
    result: dict = {"command": cmd, "handled": False, "detail": "ignored"}

    if not cmd or not chat_id:
        return result

    spec = WALLET_BALANCE_COMMANDS.get(cmd)
    if spec is None:
        result["detail"] = "unknown_command"
        return result

    tenant = resolve_tenant_by_bot_id(bot_id)
    if tenant is None:
        logger.warning("telegram_command: tenant not found for bot_id=%s command=%s", bot_id, cmd)
        result["detail"] = "tenant_not_found"
        return result

    user = resolve_user_by_telegram_id(user_id)
    try:
        tg_uid = int(str(user_id).strip()) if user_id not in (None, "") else None
    except (TypeError, ValueError):
        tg_uid = None

    try:
        text = handle_wallet_balance_command(
            spec=spec,
            tenant=tenant,
            user=user,
            recipient_id=chat_id,
            telegram_user_id=tg_uid,
        )
    except Exception:
        logger.exception(
            "telegram_command: handler failed command=%s tenant_id=%s user_id=%s",
            cmd,
            getattr(tenant, "pk", None),
            user_id,
        )
        result["detail"] = "handler_error"
        return result

    result.update({"handled": True, "detail": "ok", "reply_preview": text[:120]})
    return result
