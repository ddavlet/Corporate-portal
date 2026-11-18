"""Read/write of CardExpenseAutoRequestConfig (per corporate card wallet) for the settings API."""

from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import NotFound

from apps.modules.corporate_card.models import CardExpenseAutoRequestConfig
from apps.modules.requests.models import Request, RequestFormPaymentTypeConfig, RequestPaymentPurposeConfig
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import Wallet

EDITABLE_FIELDS = ("is_enabled", "payment_purpose", "category", "company_payer", "vendor_ref_id", "match_text")


def get_card_wallet_or_404(*, tenant, wallet_id: int) -> Wallet:
    wallet = (
        Wallet.objects.select_related("corporate_card_account")
        .filter(pk=wallet_id, tenant=tenant, wallet_type=Wallet.Type.CORPORATE_CARD)
        .first()
    )
    if wallet is None:
        raise NotFound("Корпоративная карта не найдена.")
    return wallet


def wallet_label(wallet: Wallet) -> str:
    account = getattr(wallet, "corporate_card_account", None)
    label = str(getattr(account, "label", "") or "").strip()
    return label or f"Корпоративная карта {wallet.currency}"


def active_card_payment_purposes(tenant) -> list[dict]:
    rows = (
        RequestPaymentPurposeConfig.objects.filter(
            payment_type_config__config__tenant=tenant,
            payment_type_config__payment_type=Request.PAYMENT_TYPE_CARD,
            is_active=True,
        )
        .order_by("name", "id")
        .values_list("name", "category")
    )
    seen: set[str] = set()
    result: list[dict] = []
    for name, category in rows:
        name_s = str(name or "").strip()
        if not name_s or name_s in seen:
            continue
        seen.add(name_s)
        result.append({"name": name_s, "category": str(category or "").strip()})
    return result


def tenant_vendors(tenant):
    return Vendor.objects.filter(tenant=tenant).order_by("name", "id")


def default_card_company_payer(tenant) -> str:
    return (
        RequestFormPaymentTypeConfig.objects.filter(config__tenant=tenant, payment_type=Request.PAYMENT_TYPE_CARD)
        .values_list("default_company_payer", flat=True)
        .first()
        or ""
    )


def card_auto_request_config_payload(*, tenant, wallet: Wallet) -> dict:
    config = CardExpenseAutoRequestConfig.objects.filter(wallet=wallet, tenant=tenant).first()
    return {
        "wallet_id": wallet.id,
        "wallet_label": wallet_label(wallet),
        "currency": wallet.currency,
        "is_enabled": bool(config and config.is_enabled),
        "payment_purpose": config.payment_purpose if config else "",
        "category": config.category if config else "",
        "company_payer": config.company_payer if config else "",
        "vendor_ref_id": config.vendor_ref_id if config else None,
        "match_text": config.match_text if config else "",
        "updated_at": config.updated_at if config else None,
        "options": {
            "payment_purposes": active_card_payment_purposes(tenant),
            "vendors": list(tenant_vendors(tenant).values("id", "name")),
            "default_company_payer": default_card_company_payer(tenant),
        },
    }


def current_card_auto_request_values(*, tenant, wallet: Wallet) -> dict:
    config = CardExpenseAutoRequestConfig.objects.filter(wallet=wallet, tenant=tenant).first()
    if config is None:
        return {
            "is_enabled": False,
            "payment_purpose": "",
            "category": "",
            "company_payer": "",
            "vendor_ref_id": None,
            "match_text": "",
        }
    return {field: getattr(config, field) for field in EDITABLE_FIELDS}


def save_card_auto_request_config(*, tenant, wallet: Wallet, data: dict, actor) -> None:
    with transaction.atomic():
        config, _ = CardExpenseAutoRequestConfig.objects.select_for_update().get_or_create(
            wallet=wallet,
            defaults={"tenant": tenant},
        )
        for field in EDITABLE_FIELDS:
            if field in data:
                setattr(config, field, data[field])
        config.updated_by = actor
        config.save()
