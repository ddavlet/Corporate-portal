from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.wallets.resolution import (
    get_or_create_bank_wallet,
    get_or_create_cash_wallet,
    get_or_create_corporate_wallet,
)
from apps.modules.wallets.services import wallet_balance_payload
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


class WalletBalanceServiceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u", password="x")
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")

    def test_wallet_balance_payload_shape(self):
        dt = timezone.now()
        CashExpense.objects.create(
            tenant=self.tenant,
            external_id="e1",
            confirmed=True,
            title="x",
            amount=Decimal("5.00"),
            currency="UZS",
            wallet=self.wallet,
            expense_at=dt,
            expense_year=dt.year,
            expense_month=dt.month,
            expense_day=dt.day,
            note="",
            payload={},
            created_by=self.user,
        )
        payload = wallet_balance_payload(wallet=self.wallet)
        self.assertEqual(payload["wallet_id"], self.wallet.id)
        self.assertIn("movements_net", payload)
        self.assertIn("current_balance", payload)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class WalletsApiTests(APITestCase):
    def setUp(self):
        su, _ = User.objects.update_or_create(
            pk=1,
            defaults={"username": "n8n_system"},
        )
        if not su.has_usable_password():
            su.set_unusable_password()
            su.save(update_fields=["password"])
        self.system_user = su

        self.tenant = Tenant.objects.create(name="Acme", subdomain="wallets", is_active=True)
        self.admin = User.objects.create_user(username="admin_wallets", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        for key in ("cash", "bank", "corporate_card", "wallets"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)

        self.wallet_cash = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        self.wallet_bank = get_or_create_bank_wallet(tenant=self.tenant)
        self.wallet_corp = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")

    def _headers(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {
            "HTTP_HOST": "wallets.example.com",
            "HTTP_AUTHORIZATION": f"Bearer {token}",
        }

    def test_cash_balances_returns_wallet_row(self):
        res = self.client.get("/api/cash/balances/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertTrue(any(row["wallet_id"] == self.wallet_cash.id for row in data))

    def test_cash_balances_requires_cash_module(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="cash").update(is_enabled=False)
        res = self.client.get("/api/cash/balances/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 403)

    def test_bank_balances_returns_wallet_row(self):
        res = self.client.get("/api/bank/balances/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertTrue(any(row["wallet_id"] == self.wallet_bank.id for row in data))

    def test_bank_balances_requires_bank_module(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="bank").update(is_enabled=False)
        res = self.client.get("/api/bank/balances/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 403)

    def test_corporate_card_balances_returns_wallet_row(self):
        res = self.client.get("/api/corporate-card/balances/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertTrue(any(row["wallet_id"] == self.wallet_corp.id for row in data))

    def test_corporate_card_balances_requires_corporate_card_module(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="corporate_card").update(
            is_enabled=False
        )
        res = self.client.get("/api/corporate-card/balances/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 403)

    def test_duplicate_cash_register_currency_allowed(self):
        res = self.client.post(
            "/api/wallets/cash-registers/",
            {"currency": "UZS", "name": "Second"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json().get("currency"), "UZS")

    def test_patch_wallet_opening_balance(self):
        res = self.client.patch(
            f"/api/wallets/wallets/{self.wallet_cash.id}/",
            {"opening_balance": "123.45"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res.status_code, 200)
        self.wallet_cash.refresh_from_db()
        self.assertEqual(str(self.wallet_cash.opening_balance), "123.45")

    def test_cashier_cannot_create_cash_register(self):
        cashier = User.objects.create_user(username="cashier_w", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=cashier, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=cashier, role=TenantUserRole.ROLE_CASHIER)
        res = self.client.post(
            "/api/wallets/cash-registers/",
            {"currency": "EUR", "name": "EUR desk"},
            format="json",
            **self._headers(cashier),
        )
        self.assertEqual(res.status_code, 403)

    def test_hidden_cash_wallet_is_excluded_from_cash_section_lists(self):
        self.wallet_cash.is_visible_in_cash_section = False
        self.wallet_cash.save(update_fields=["is_visible_in_cash_section"])
        dt = timezone.now()
        CashExpense.objects.create(
            tenant=self.tenant,
            external_id="hidden-exp-1",
            confirmed=True,
            title="Hidden expense",
            amount=Decimal("10.00"),
            currency="UZS",
            wallet=self.wallet_cash,
            expense_at=dt,
            expense_year=dt.year,
            expense_month=dt.month,
            expense_day=dt.day,
            note="",
            payload={},
            created_by=self.admin,
        )
        CashRevenue.objects.create(
            tenant=self.tenant,
            external_id="hidden-rev-1",
            confirmed=True,
            total_sum=Decimal("25.00"),
            currency="UZS",
            wallet=self.wallet_cash,
            operation="Hidden revenue",
            payload={},
            created_by=self.admin,
        )

        balances_res = self.client.get("/api/cash/balances/", **self._headers(self.admin))
        expenses_res = self.client.get("/api/cash/expenses/", **self._headers(self.admin))
        revenues_res = self.client.get("/api/cash/revenues/", **self._headers(self.admin))

        self.assertEqual(balances_res.status_code, 200)
        self.assertEqual(expenses_res.status_code, 200)
        self.assertEqual(revenues_res.status_code, 200)

        balances_rows = balances_res.json()
        expenses_payload = expenses_res.json()
        revenues_payload = revenues_res.json()
        expense_rows = (
            expenses_payload
            if isinstance(expenses_payload, list)
            else expenses_payload.get("results", [])
        )
        revenue_rows = (
            revenues_payload
            if isinstance(revenues_payload, list)
            else revenues_payload.get("results", [])
        )

        self.assertFalse(any(row["wallet_id"] == self.wallet_cash.id for row in balances_rows))
        self.assertFalse(any(row["wallet_id"] == self.wallet_cash.id for row in expense_rows))
        self.assertFalse(any(row["wallet_id"] == self.wallet_cash.id for row in revenue_rows))

    def test_bank_accounts_list_includes_existing(self):
        res = self.client.get("/api/wallets/bank-accounts/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        ids = {r["wallet_id"] for r in rows}
        self.assertIn(self.wallet_bank.id, ids)

    def test_bank_account_second_create_rejected(self):
        res = self.client.post(
            "/api/wallets/bank-accounts/",
            {"label": "Дубликат"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res.status_code, 400)

    def test_corporate_card_accounts_list_and_duplicate_currency_allowed(self):
        res = self.client.get("/api/wallets/corporate-card-accounts/", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        self.assertTrue(any(r["wallet_id"] == self.wallet_corp.id for r in rows))

        dup = self.client.post(
            "/api/wallets/corporate-card-accounts/",
            {"currency": "UZS", "label": "Другой"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(dup.status_code, 201, dup.content)
