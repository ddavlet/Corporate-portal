"""Shared test fixtures for dividend_payouts tests (not a test module itself)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.modules.dividend_payouts.models import DividendPayoutRule
from apps.modules.investments.models import CbuExchangeRate, InvestReturn
from apps.modules.requests.models import (
    Request,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

User = get_user_model()

FOUNDER_PURPOSE = "Дивиденды учредителю"
PARTNER_PURPOSE = "Дивиденды партнерам"


class DividendPayoutFixtures:
    """Mixin for APITestCase/TestCase: call self.make_fixtures() in setUp."""

    host = "lemonaqua.example.com"

    def make_fixtures(self) -> None:
        self.system_user, _ = User.objects.update_or_create(pk=1, defaults={"username": "system"})
        self.tenant = Tenant.objects.create(name="Lemonfit AQUA", subdomain="lemonaqua", is_active=True)
        self.admin = User.objects.create_user(username="dp-admin", password="x", full_name="Админ Главный")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        # Payout amounts are validated against the CBU archive (no network): one rate is enough.
        CbuExchangeRate.objects.create(date=date(2026, 1, 5), usd_uzs_rate=Decimal("12500.000000"))

    def make_rule(self, *, tenant=None, purpose: str = FOUNDER_PURPOSE, **overrides) -> DividendPayoutRule:
        data = {
            "tenant": tenant or self.tenant,
            "payment_purpose": purpose,
            "return_type": InvestReturn.ReturnType.PRINCIPAL,
            "recipient": InvestReturn.Recipient.INVESTOR,
            "is_active": True,
        }
        data.update(overrides)
        return DividendPayoutRule.objects.create(**data)

    def make_request(self, **overrides) -> Request:
        data = {
            "tenant": self.tenant,
            "created_by": self.admin,
            "billing_date": date(2026, 10, 15),
            "amount": Decimal("2500.00"),
            "currency": "USD",
            "payment_type": Request.PAYMENT_TYPE_TRANSFER,
            "payment_purpose": FOUNDER_PURPOSE,
            "title": "Дивиденды",
            "vendor": "Иванов Иван",
            "description": "Выплата дивидендов",
            "category": "Дивиденды",
            "company_payer": "Lemonfit AQUA",
            "status": Request.STATUS_PAYED,
            "payed_at": 20261106,
        }
        data.update(overrides)
        return Request.objects.create(**data)

    def make_purpose(self, *, tenant=None, name: str, payment_type: str = Request.PAYMENT_TYPE_TRANSFER,
                     category: str = "Дивиденды", is_active: bool = True) -> RequestPaymentPurposeConfig:
        config, _ = RequestFormConfig.objects.get_or_create(tenant=tenant or self.tenant)
        pt_config, _ = RequestFormPaymentTypeConfig.objects.get_or_create(config=config, payment_type=payment_type)
        return RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_config, name=name, category=category, is_active=is_active
        )
