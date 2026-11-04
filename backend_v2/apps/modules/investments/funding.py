"""Инвестиционный режим тенанта: настройки, политики типов заявок «Инвест. наличные/перечисление».

Политики регистрируются в реестре `requests.payment_type_policies` при старте приложения
(`InvestmentsModuleConfig.ready`), поэтому `requests` не импортирует `investments`.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.investments.models import (
    InvestmentFundingConfig,
    InvestmentProjectApprovalConfig,
)
from apps.modules.requests.models import Request, RequestFormConfig, RequestFormPaymentTypeConfig
from apps.modules.requests.payment_type_policies import (
    register_payment_type_policy,
    register_request_mutation_guard,
)
from apps.modules.wallets.models import Wallet
from apps.tenants.models import TenantModuleConfig

INVESTOR_DEPOSIT_OPERATION = "Вложение инвестора"


def is_module_enabled(tenant, module_key: str) -> bool:
    return TenantModuleConfig.objects.filter(tenant=tenant, module_key=module_key, is_enabled=True).exists()


def get_enabled_funding_config(tenant) -> InvestmentFundingConfig | None:
    """Конфиг инвестиционного режима, только если он включён и модуль investments активен."""
    if tenant is None or not is_module_enabled(tenant, "investments"):
        return None
    return (
        InvestmentFundingConfig.objects.filter(tenant=tenant, is_enabled=True)
        .select_related("cash_wallet__cash_register", "bank_wallet__bank_account")
        .first()
    )


def has_active_project_approval_chain(tenant) -> bool:
    cfg = InvestmentProjectApprovalConfig.objects.filter(tenant=tenant, is_enabled=True).first()
    return bool(cfg and cfg.steps.filter(is_enabled=True).exists())


def wallet_label(wallet: Wallet) -> str:
    if wallet.wallet_type == Wallet.Type.BANK:
        account = wallet.bank_account
        if account is not None:
            return account.label or account.account_no or "Счёт"
        return "Счёт"
    register = wallet.cash_register
    if register is not None and register.name:
        return register.name
    return wallet.currency


class _InvestPolicyBase:
    payment_type: str = ""

    def _wallet(self, cfg: InvestmentFundingConfig) -> Wallet | None:
        raise NotImplementedError

    def is_available(self, *, tenant) -> bool:
        cfg = get_enabled_funding_config(tenant)
        return cfg is not None and self._wallet(cfg) is not None

    def normalize_attrs(self, *, tenant, attrs: dict, instance: Request | None) -> dict:
        type_changed = instance is None or (
            "payment_type" in attrs and attrs["payment_type"] != instance.payment_type
        )
        if not type_changed:
            # Существующая заявка: касса/счёт зафиксированы при создании и не меняются ни клиентом,
            # ни перенастройкой режима.
            current = instance.wallet_ref
            attrs["wallet_ref"] = current
            if current is not None and "currency" in attrs:
                self._check_currency(attrs=attrs, instance=instance, wallet=current)
            return attrs
        cfg = get_enabled_funding_config(tenant)
        if cfg is None:
            # Создание блокирует is_available; здесь только страховка.
            return attrs
        wallet = self._wallet(cfg)
        if wallet is None:
            return attrs
        attrs["wallet_ref"] = wallet
        self._check_currency(attrs=attrs, instance=instance, wallet=wallet)
        return attrs

    def _check_currency(self, *, attrs: dict, instance: Request | None, wallet: Wallet) -> None:
        return None

    def form_hint(self, *, tenant) -> dict | None:
        cfg = get_enabled_funding_config(tenant)
        wallet = self._wallet(cfg) if cfg is not None else None
        if wallet is None:
            return None
        return {
            "wallet_id": wallet.id,
            "wallet_label": wallet_label(wallet),
            "currency": wallet.currency if wallet.wallet_type == Wallet.Type.CASH else None,
        }


class InvestCashPolicy(_InvestPolicyBase):
    payment_type = Request.PAYMENT_TYPE_INVEST_CASH

    def _wallet(self, cfg):
        return cfg.cash_wallet

    def _check_currency(self, *, attrs, instance, wallet):
        currency = attrs.get("currency") or (instance.currency if instance is not None else None)
        if currency and currency != wallet.currency:
            raise ValidationError(
                {"currency": f"Валюта заявки должна совпадать с валютой инвестиционной кассы ({wallet.currency})."}
            )


class InvestTransferPolicy(_InvestPolicyBase):
    payment_type = Request.PAYMENT_TYPE_INVEST_TRANSFER

    def _wallet(self, cfg):
        return cfg.bank_wallet


def _ensure_invest_form_configs(*, tenant, user, cash_wallet: Wallet | None) -> None:
    """Типы «Инвест. …» должны быть в форме заявок тенанта, иначе они не появятся в form-options."""
    form_cfg, _ = RequestFormConfig.objects.get_or_create(tenant=tenant, defaults={"updated_by": user})
    for payment_type in (Request.PAYMENT_TYPE_INVEST_CASH, Request.PAYMENT_TYPE_INVEST_TRANSFER):
        defaults = {"is_enabled": True}
        if payment_type == Request.PAYMENT_TYPE_INVEST_CASH and cash_wallet is not None:
            defaults["default_currency"] = cash_wallet.currency
        pt_cfg, created = RequestFormPaymentTypeConfig.objects.get_or_create(
            config=form_cfg, payment_type=payment_type, defaults=defaults
        )
        if not created and not pt_cfg.is_enabled:
            pt_cfg.is_enabled = True
            pt_cfg.save(update_fields=["is_enabled"])


@transaction.atomic
def apply_funding_config(*, tenant, user, is_enabled: bool, cash_wallet, bank_wallet) -> InvestmentFundingConfig:
    cfg, _ = InvestmentFundingConfig.objects.select_for_update().get_or_create(tenant=tenant)
    cfg.is_enabled = is_enabled
    cfg.cash_wallet = cash_wallet
    cfg.bank_wallet = bank_wallet
    cfg.updated_by = user
    if is_enabled and cfg.enabled_at is None:
        cfg.enabled_at = timezone.now()
    cfg.save()
    if is_enabled:
        _ensure_invest_form_configs(tenant=tenant, user=user, cash_wallet=cash_wallet)
    return cfg


def register_funding_policies() -> None:
    """Идемпотентно: повторная регистрация просто заменяет записи реестра."""
    register_payment_type_policy(Request.PAYMENT_TYPE_INVEST_CASH, InvestCashPolicy())
    register_payment_type_policy(Request.PAYMENT_TYPE_INVEST_TRANSFER, InvestTransferPolicy())
    # Импорт здесь: funding_pool сам импортирует этот модуль.
    from apps.modules.investments.funding_pool import collected_request_mutation_guard

    # Реестр не дублирует одну и ту же функцию — повторный вызов безопасен.
    register_request_mutation_guard(collected_request_mutation_guard)
