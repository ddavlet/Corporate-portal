"""Shared test fixtures for cash_desk tests (not a test module itself)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.modules.cash_desk.models import CashDeskConfig
from apps.modules.requests.models import Request
from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.modules.wallets.models import CashRegister, Wallet
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

User = get_user_model()


def _make_cash_wallet(tenant, *, currency: str, name: str, default: bool, sort_order: int) -> Wallet:
    register = CashRegister.objects.create(
        tenant=tenant,
        currency=currency,
        name=name,
        is_active=True,
        is_default_for_currency=default,
        sort_order=sort_order,
    )
    return Wallet.objects.create(
        tenant=tenant,
        wallet_type=Wallet.Type.CASH,
        currency=currency,
        opening_balance=0,
        cash_register=register,
    )


class CashDeskFixtures:
    """Mixin for APITestCase/TestCase: call self.make_fixtures() in setUp."""

    host = "lemonaqua.example.com"

    def make_fixtures(self) -> None:
        User.objects.update_or_create(pk=1, defaults={"username": "system"})
        self.tenant = Tenant.objects.create(name="Lemonfit AQUA", subdomain="lemonaqua", is_active=True)
        self.admin = User.objects.create_user(
            username="cd-admin", password="x", full_name="Админ Главный", telegram_chat_id=92000, telegram_from_id=92000
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)

        self.main = _make_cash_wallet(
            self.tenant, currency="UZS", name="Основная касса (касса)", default=True, sort_order=0
        )
        self.safe = _make_cash_wallet(self.tenant, currency="UZS", name="Сейф", default=False, sort_order=1)
        self.usd = _make_cash_wallet(self.tenant, currency="USD", name="Касса USD", default=True, sort_order=2)

        self.group = TenantTelegramChat.objects.create(
            tenant=self.tenant, name="Касса Aqua", chat_id="-100500", created_by=self.admin
        )
        self.config = CashDeskConfig.objects.create(
            tenant=self.tenant, is_active=True, telegram_chat=self.group, updated_by=self.admin
        )

    def make_request(self, **overrides) -> Request:
        data = {
            "tenant": self.tenant,
            "created_by": self.admin,
            "billing_date": date(2026, 11, 6),
            "amount": Decimal("1500000.00"),
            "currency": "UZS",
            "payment_type": "Наличные",
            "payment_purpose": "Хозтовары",
            "title": "Покупка",
            "vendor": "ООО Ромашка",
            "description": "Описание",
            "category": "Хозяйственные",
            "company_payer": "Lemonfit AQUA",
            "wallet_ref": None,
            "status": Request.STATUS_PAYED,
            "payed_at": 20261106,
        }
        data.update(overrides)
        return Request.objects.create(**data)
