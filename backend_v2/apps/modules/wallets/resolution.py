"""Create or resolve Wallet rows for movement lines (tenant + channel + currency)."""

from __future__ import annotations

from apps.tenants.models import Tenant

from apps.modules.wallets.models import BankAccount, CashRegister, CorporateCardAccount, Wallet


def normalized_currency(code: str | None) -> str:
    c = (code or "").strip()
    return c if c else "UZS"


def get_or_create_cash_wallet(*, tenant: Tenant, currency: str | None) -> Wallet:
    cur = normalized_currency(currency)
    reg, _ = CashRegister.objects.get_or_create(
        tenant=tenant,
        currency=cur,
        defaults={
            "name": "Основная",
            "is_active": True,
            "is_default_for_currency": True,
        },
    )
    w, _ = Wallet.objects.get_or_create(
        cash_register=reg,
        defaults={
            "tenant": tenant,
            "wallet_type": Wallet.Type.CASH,
            "currency": cur,
            "opening_balance": 0,
        },
    )
    return w


def get_or_create_corporate_wallet(*, tenant: Tenant, currency: str | None) -> Wallet:
    cur = normalized_currency(currency)
    acc, _ = CorporateCardAccount.objects.get_or_create(
        tenant=tenant,
        currency=cur,
        defaults={"label": "Основная"},
    )
    w, _ = Wallet.objects.get_or_create(
        corporate_card_account=acc,
        defaults={
            "tenant": tenant,
            "wallet_type": Wallet.Type.CORPORATE_CARD,
            "currency": cur,
            "opening_balance": 0,
        },
    )
    return w


def get_or_create_bank_wallet(*, tenant: Tenant) -> Wallet:
    ba, _ = BankAccount.objects.get_or_create(
        tenant=tenant,
        defaults={"label": "Основной", "account_no": "", "mfo": ""},
    )
    w, _ = Wallet.objects.get_or_create(
        bank_account=ba,
        defaults={
            "tenant": tenant,
            "wallet_type": Wallet.Type.BANK,
            "currency": "UZS",
            "opening_balance": 0,
        },
    )
    return w


def resolve_wallet_for_cash(*, tenant: Tenant, currency: str | None, wallet_id: int | None) -> Wallet:
    if wallet_id is not None:
        w = Wallet.objects.filter(
            pk=wallet_id,
            tenant=tenant,
            wallet_type=Wallet.Type.CASH,
        ).first()
        if not w:
            raise ValueError("Invalid wallet for cash.")
        return w
    return get_or_create_cash_wallet(tenant=tenant, currency=currency)


def resolve_wallet_for_bank(*, tenant: Tenant, wallet_id: int | None) -> Wallet:
    if wallet_id is not None:
        w = Wallet.objects.filter(
            pk=wallet_id,
            tenant=tenant,
            wallet_type=Wallet.Type.BANK,
        ).first()
        if not w:
            raise ValueError("Invalid wallet for bank.")
        return w
    return get_or_create_bank_wallet(tenant=tenant)


def resolve_wallet_for_corporate(*, tenant: Tenant, currency: str | None, wallet_id: int | None) -> Wallet:
    if wallet_id is not None:
        w = Wallet.objects.filter(
            pk=wallet_id,
            tenant=tenant,
            wallet_type=Wallet.Type.CORPORATE_CARD,
        ).first()
        if not w:
            raise ValueError("Invalid wallet for corporate card.")
        return w
    return get_or_create_corporate_wallet(tenant=tenant, currency=currency)
