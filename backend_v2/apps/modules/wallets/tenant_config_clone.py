"""
Wallets part of `clone_tenant_config` (see apps.tenants.config_clone): the
branch's cash registers by name — currency, code, order and default flag —
each with its own cash wallet starting from a zero opening balance. Balances
and movements are branch data and are not copied; neither are bank accounts
or corporate cards (their numbers belong to the branch).

Copied only while the target has no cash registers at all, so a re-run or a
target that already set up its own registers is left as is.
"""

from __future__ import annotations

from apps.modules.wallets.models import CashRegister, Wallet


def clone(ctx) -> None:
    if CashRegister.objects.filter(tenant=ctx.target).exists():
        return
    source_registers = CashRegister.objects.filter(tenant=ctx.source).select_related("wallet").order_by("sort_order", "id")
    for src in source_registers:
        reg = CashRegister.objects.create(
            tenant=ctx.target,
            currency=src.currency,
            name=src.name,
            code=src.code,
            description=src.description,
            is_active=src.is_active,
            sort_order=src.sort_order,
            is_default_for_currency=src.is_default_for_currency,
        )
        source_wallet = getattr(src, "wallet", None)
        Wallet.objects.create(
            tenant=ctx.target,
            wallet_type=Wallet.Type.CASH,
            currency=reg.currency,
            cash_register=reg,
            opening_balance=0,
            is_visible_in_cash_section=source_wallet.is_visible_in_cash_section if source_wallet else True,
        )
        ctx.change(f"Касса «{reg.name}» ({reg.currency}) добавлена с нулевым начальным остатком.")
