from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.common.test_utils import list_results
from apps.modules.requests.expense_refs import expense_ref_target_for
from apps.modules.requests.models import Request
from apps.modules.requests.payment_type_families import canonical_payment_type, expand_with_invest_types
from apps.modules.requests.services import create_expense_for_request_payment
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


class PaymentTypeFamiliesTests(SimpleTestCase):
    def test_canonical_payment_type_maps_invest_types(self):
        self.assertEqual(canonical_payment_type("Инвест. наличные"), "Наличные")
        self.assertEqual(canonical_payment_type("Инвест. перечисление"), "Перечисление")
        self.assertEqual(canonical_payment_type("Пополнение"), "Пополнение")

    def test_expand_with_invest_types(self):
        self.assertEqual(
            expand_with_invest_types(["Наличные", "Перечисление"]),
            ["Наличные", "Перечисление", "Инвест. наличные", "Инвест. перечисление"],
        )
        self.assertEqual(expand_with_invest_types(["Пополнение"]), ["Пополнение"])

    def test_expense_ref_target_for_invest_types(self):
        self.assertEqual(expense_ref_target_for(payment_type="Инвест. наличные", category=""), "cash")
        self.assertEqual(expense_ref_target_for(payment_type="Инвест. перечисление", category=""), "bank")


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestPaymentTypeVisibilityTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="InvVis", subdomain="invvis", is_active=True)
        self.admin = User.objects.create_user(username="iv_admin", password="x")
        self.cashier = User.objects.create_user(username="iv_cash", password="x")
        for u in (self.admin, self.cashier):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.cashier, role=TenantUserRole.ROLE_CASHIER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "invvis.example.com"
        for idx, pt in enumerate(
            [Request.PAYMENT_TYPE_INVEST_CASH, Request.PAYMENT_TYPE_INVEST_TRANSFER], start=1
        ):
            Request.objects.create(
                tenant=self.tenant,
                created_by=self.admin,
                requester=self.admin,
                title=f"Inv {idx}",
                description="",
                amount=Decimal("100"),
                currency="UZS",
                payment_type=pt,
                urgency=Request.URGENCY_NORMAL,
                billing_date=date(2026, 1, 1),
                status=Request.STATUS_DRAFT,
                submitted_at=timezone.now(),
                company_payer="",
            )

    def test_cashier_sees_invest_cash_requests(self):
        self.client.force_authenticate(self.cashier)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        visible_types = {row["payment_type"] for row in list_results(res)}
        self.assertEqual(visible_types, {Request.PAYMENT_TYPE_INVEST_CASH})


class InvestPayoutWalletTests(APITestCase):
    """create_expense_for_request_payment: счёт выплаты для инвест-типов."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="InvPay", subdomain="invpay", is_active=True)
        self.admin = User.objects.create_user(username="ip_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        for key in ("bank", "cash"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)

    def _request(self, payment_type, wallet_ref=None):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Pay",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=payment_type,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_APPROVED,
            submitted_at=timezone.now(),
            company_payer="",
            wallet_ref=wallet_ref,
        )

    def _bank_wallet(self, label, is_default):
        from apps.modules.wallets.models import BankAccount, Wallet

        account = BankAccount.objects.create(tenant=self.tenant, label=label, is_default=is_default)
        return Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=account
        )

    def test_invest_cash_payout_creates_cash_expense_in_wallet_ref(self):
        from apps.modules.cashier.models import CashExpense
        from apps.modules.wallets.models import CashRegister, Wallet

        CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Default", is_default_for_currency=True)
        other_register = CashRegister.objects.create(
            tenant=self.tenant, currency="UZS", name="Other", is_default_for_currency=False
        )
        other_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=other_register
        )
        req = self._request(Request.PAYMENT_TYPE_INVEST_CASH, wallet_ref=other_wallet)

        target, expense_id = create_expense_for_request_payment(request_obj=req, actor_user=self.admin)

        self.assertEqual(target, "cash")
        self.assertEqual(CashExpense.objects.get(pk=expense_id).wallet_id, other_wallet.id)
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_target, "cash")

    def test_invest_transfer_payout_uses_request_bank_wallet(self):
        from apps.modules.bank_expenses.models import BankExpense

        default_wallet = self._bank_wallet("Default", True)
        request_wallet = self._bank_wallet("Invest", False)
        req = self._request(Request.PAYMENT_TYPE_INVEST_TRANSFER, wallet_ref=request_wallet)

        target, expense_id = create_expense_for_request_payment(request_obj=req, actor_user=self.admin)

        self.assertEqual(target, "bank")
        expense = BankExpense.objects.get(pk=expense_id)
        self.assertEqual(expense.wallet_id, request_wallet.id)
        self.assertNotEqual(expense.wallet_id, default_wallet.id)

    def test_regular_transfer_payout_unchanged(self):
        from apps.modules.bank_expenses.models import BankExpense

        default_wallet = self._bank_wallet("Default", True)
        req = self._request(Request.PAYMENT_TYPE_TRANSFER)

        target, expense_id = create_expense_for_request_payment(request_obj=req, actor_user=self.admin)

        self.assertEqual(target, "bank")
        self.assertEqual(BankExpense.objects.get(pk=expense_id).wallet_id, default_wallet.id)
