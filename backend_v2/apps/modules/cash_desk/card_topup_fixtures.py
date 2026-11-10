"""Shared test fixtures for card top-up tests (not a test module itself)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.modules.cash_desk.fixtures import CashDeskFixtures
from apps.modules.cash_desk.models import CardTopupNotifyConfig
from apps.modules.requests.models import Request
from apps.modules.wallets.models import CorporateCardAccount, Wallet
from apps.tenants.models import TenantMembership

User = get_user_model()


def make_card_wallet(tenant, *, label: str, currency: str = "UZS", opening_balance: str = "0") -> Wallet:
    account = CorporateCardAccount.objects.create(tenant=tenant, currency=currency, label=label)
    return Wallet.objects.create(
        tenant=tenant,
        wallet_type=Wallet.Type.CORPORATE_CARD,
        currency=currency,
        opening_balance=Decimal(opening_balance),
        corporate_card_account=account,
    )


class CardTopupFixtures(CashDeskFixtures):
    """Adds recipients, a corporate card and an active top-up config on top of CashDeskFixtures."""

    def make_topup_fixtures(self) -> None:
        self.make_fixtures()
        self.accountant = User.objects.create_user(
            username="ct-acc", password="x", full_name="Илхом Уктамов", telegram_chat_id=93001, telegram_from_id=93001
        )
        self.no_tg = User.objects.create_user(username="ct-notg", password="x", full_name="Без Телеграма")
        for user in (self.accountant, self.no_tg):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        self.card = make_card_wallet(self.tenant, label="Humo Neuron", opening_balance="2500000")
        self.topup_config = CardTopupNotifyConfig.objects.create(
            tenant=self.tenant, is_active=True, updated_by=self.admin
        )
        self.topup_config.recipients.set([self.accountant])

    def make_topup_request(self, **overrides) -> Request:
        data = {
            "payment_type": Request.PAYMENT_TYPE_TOPUP,
            "payment_purpose": "Пополнение корпоративной карты",
            "amount": Decimal("5000000.00"),
            "wallet_ref": None,
        }
        data.update(overrides)
        return self.make_request(**data)
