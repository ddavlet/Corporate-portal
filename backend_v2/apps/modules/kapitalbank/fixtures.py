"""Shared test fixtures for kapitalbank tests (not a test module itself)."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.modules.wallets.models import CorporateCardAccount
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account, get_or_create_corporate_wallet
from apps.tenants.models import Tenant, TenantModuleConfig

User = get_user_model()

MFO = "01158"
ACCOUNT_1 = "20208000504843803001"
ACCOUNT_2 = "20208000904843803004"
CARD_REF = "8600490000000001"


class KapitalbankFixtures:
    """Mixin for TestCase: call self.make_fixtures() in setUp."""

    def make_fixtures(self) -> None:
        User.objects.update_or_create(pk=1, defaults={"username": "system"})
        self.tenant = Tenant.objects.create(name="Kolberg Plus", subdomain="kp", is_active=True)
        self.owner = User.objects.create_user(
            username="kb-owner", password="x", full_name="Владелец", telegram_chat_id=1387986, telegram_from_id=1387986
        )
        self.wallet1 = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no=ACCOUNT_1, mfo=MFO)
        self.wallet2 = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no=ACCOUNT_2, mfo=MFO)
        self.bank_account1 = self.wallet1.bank_account
        self.bank_account2 = self.wallet2.bank_account
        self.card_wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        self.card_account = self.card_wallet.corporate_card_account
        CorporateCardAccount.objects.filter(pk=self.card_account.pk).update(external_ref=CARD_REF)
        self.card_account.refresh_from_db()
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="bank", is_enabled=True)
