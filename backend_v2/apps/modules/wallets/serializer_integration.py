"""Assign `wallet` on movement serializers (tenant + channel + optional explicit id)."""

from __future__ import annotations

from rest_framework import serializers

from apps.modules.wallets.resolution import (
    normalized_currency,
    resolve_wallet_for_bank,
    resolve_wallet_for_cash,
    resolve_wallet_for_corporate,
)


def assign_wallet_for_cash_movement(*, instance, tenant, attrs: dict) -> dict:
    currency = attrs.get("currency")
    if currency is None and instance is not None:
        currency = instance.currency

    has_wallet = "wallet" in attrs
    explicit = attrs.pop("wallet", None) if has_wallet else None

    if instance is None:
        _set_cash(attrs, tenant, currency, explicit)
        return attrs

    if has_wallet:
        _set_cash(attrs, tenant, currency, explicit)
        return attrs

    if "currency" in attrs:
        new_cur = normalized_currency(attrs["currency"])
        old_cur = normalized_currency(instance.currency)
        if new_cur != old_cur:
            _set_cash(attrs, tenant, attrs["currency"], None)
    return attrs


def _set_cash(attrs: dict, tenant, currency, explicit) -> None:
    try:
        attrs["wallet"] = resolve_wallet_for_cash(
            tenant=tenant,
            currency=currency,
            wallet_id=explicit.pk if explicit else None,
        )
    except ValueError as e:
        raise serializers.ValidationError({"wallet_id": str(e)}) from e


def assign_wallet_for_bank_movement(*, instance, tenant, attrs: dict) -> dict:
    has_wallet = "wallet" in attrs
    explicit = attrs.pop("wallet", None) if has_wallet else None

    if instance is None:
        _set_bank(attrs, tenant, explicit)
        return attrs

    if has_wallet:
        _set_bank(attrs, tenant, explicit)
    return attrs


def _set_bank(attrs: dict, tenant, explicit) -> None:
    try:
        attrs["wallet"] = resolve_wallet_for_bank(
            tenant=tenant,
            wallet_id=explicit.pk if explicit else None,
        )
    except ValueError as e:
        raise serializers.ValidationError({"wallet_id": str(e)}) from e


def assign_wallet_for_corporate_movement(*, instance, tenant, attrs: dict) -> dict:
    currency = attrs.get("currency")
    if currency is None and instance is not None:
        currency = instance.currency

    has_wallet = "wallet" in attrs
    explicit = attrs.pop("wallet", None) if has_wallet else None

    if instance is None:
        _set_corporate(attrs, tenant, currency, explicit)
        return attrs

    if has_wallet:
        _set_corporate(attrs, tenant, currency, explicit)
        return attrs

    if "currency" in attrs:
        new_cur = normalized_currency(attrs["currency"])
        old_cur = normalized_currency(instance.currency)
        if new_cur != old_cur:
            _set_corporate(attrs, tenant, attrs["currency"], None)
    return attrs


def _set_corporate(attrs: dict, tenant, currency, explicit) -> None:
    try:
        attrs["wallet"] = resolve_wallet_for_corporate(
            tenant=tenant,
            currency=currency,
            wallet_id=explicit.pk if explicit else None,
        )
    except ValueError as e:
        raise serializers.ValidationError({"wallet_id": str(e)}) from e
