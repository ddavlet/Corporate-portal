"""Shared test fixtures for cash_withdrawals tests (not a test module itself)."""

from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.modules.cash_withdrawals.models import (
    CashWithdrawalAlertRecipient,
    CashWithdrawalConfig,
    CashWithdrawalConfirmer,
    CashWithdrawalReceipt,
    CashWithdrawalRule,
)
from apps.modules.requests.models import Request
from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

User = get_user_model()

GATEWAY_PATH = "apps.modules.telegram_approvals.services.post_messaging_gateway"
PURPOSE = "Снятие наличных с банка"


def gateway_ok(start: int = 5000):
    """side_effect for the patched gateway: every call returns a fresh message_id."""
    counter = itertools.count(start)
    return lambda **kwargs: {"message_id": next(counter)}


class CashWithdrawalFixtures:
    """Mixin for APITestCase/TestCase: call self.make_fixtures() in setUp."""

    host = "lemonaqua.example.com"

    def make_fixtures(self) -> None:
        User.objects.update_or_create(pk=1, defaults={"username": "system"})
        self.tenant = Tenant.objects.create(name="Lemonfit AQUA", subdomain="lemonaqua", is_active=True)
        self.admin = User.objects.create_user(
            username="cw-admin", password="x", full_name="Админ Главный", telegram_chat_id=91000, telegram_from_id=91000
        )
        self.cashier = User.objects.create_user(
            username="cw-cashier", password="x", full_name="Иван Петров", telegram_chat_id=91001, telegram_from_id=91001
        )
        self.accountant = User.objects.create_user(
            username="cw-acc", password="x", full_name="Мария Сидорова", telegram_chat_id=91002, telegram_from_id=91002
        )
        self.outsider = User.objects.create_user(
            username="cw-out", password="x", full_name="Чужой Человек", telegram_chat_id=91003, telegram_from_id=91003
        )
        for user in (self.admin, self.cashier, self.accountant, self.outsider):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)

        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        self.wallet.cash_register.name = "Основная касса (касса)"
        self.wallet.cash_register.save(update_fields=["name"])

        self.group = TenantTelegramChat.objects.create(
            tenant=self.tenant, name="Касса Aqua", chat_id="-100500", created_by=self.admin
        )
        self.config = CashWithdrawalConfig.objects.create(
            tenant=self.tenant,
            is_active=True,
            card_telegram_chat=self.group,
            alert_after_days=3,
            alert_repeat_every_days=1,
            alert_hour=9,
            updated_by=self.admin,
        )
        CashWithdrawalConfirmer.objects.create(config=self.config, user=self.cashier)
        CashWithdrawalConfirmer.objects.create(config=self.config, user=self.accountant)
        CashWithdrawalAlertRecipient.objects.create(config=self.config, user=self.admin)
        self.rule = CashWithdrawalRule.objects.create(
            config=self.config,
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            payment_purpose=PURPOSE,
            wallet=self.wallet,
        )

    def make_request(self, **overrides) -> Request:
        data = {
            "tenant": self.tenant,
            "created_by": self.admin,
            "billing_date": date(2026, 9, 25),
            "amount": Decimal("100000000.00"),
            "currency": "UZS",
            "payment_type": Request.PAYMENT_TYPE_TRANSFER,
            "payment_purpose": PURPOSE,
            "description": "Снятие денег с банка на расходы",
            "status": Request.STATUS_PAYED,
            "payed_at": 20260925,
        }
        data.update(overrides)
        return Request.objects.create(**data)

    def make_receipt(self, request_obj: Request | None = None, **overrides) -> CashWithdrawalReceipt:
        request_obj = request_obj or self.make_request()
        data = {
            "tenant": self.tenant,
            "request": request_obj,
            "wallet": self.wallet,
            "amount": request_obj.amount,
            "currency": request_obj.currency,
        }
        data.update(overrides)
        return CashWithdrawalReceipt.objects.create(**data)
