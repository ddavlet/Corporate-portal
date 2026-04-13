from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.requests.models import Request, RequestApprovalConfig, RequestApprovalPaymentTypeConfig


User = get_user_model()


class CashierSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u", password="x")

    def test_can_create_cash_expense(self):
        dt = timezone.now()
        w = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        obj = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="exp-1",
            confirmed=True,
            title="Lunch",
            amount=10,
            currency="UZS",
            wallet=w,
            expense_at=dt,
            expense_year=dt.year,
            expense_month=dt.month,
            expense_day=dt.day,
            note="",
            payload={},
            created_by=self.user,
        )

        self.assertIsNotNone(obj.id)
        self.assertEqual(CashExpense.objects.filter(tenant=self.tenant).count(), 1)

    def test_can_create_cash_revenue(self):
        w = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        obj = CashRevenue.objects.create(
            tenant=self.tenant,
            external_id="rev-1",
            total_sum=100,
            confirmed=True,
            wallet=w,
            operation="Sale",
            payload={},
            created_by=self.user,
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class CashExpenseRequestRequiredApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="cash_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        self.appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        self.pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=self.appr_cfg,
            payment_type=Request.PAYMENT_TYPE_CASH,
            is_enabled=True,
        )

    def _headers(self):
        token = str(RefreshToken.for_user(self.admin).access_token)
        return {
            "HTTP_HOST": "acme.example.com",
            "HTTP_AUTHORIZATION": f"Bearer {token}",
        }

    def test_request_highlight_contract_scenarios(self):
        dt = timezone.now()
        required_missing = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="cash-required-missing",
            confirmed=True,
            title="Required missing",
            amount=10,
            currency="UZS",
            wallet=self.wallet,
            expense_at=dt,
            expense_year=dt.year,
            expense_month=dt.month,
            expense_day=dt.day,
            note="",
            payload={},
            created_by=self.admin,
        )
        required_paid = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="cash-required-paid",
            confirmed=True,
            title="Required paid",
            amount=20,
            currency="UZS",
            wallet=self.wallet,
            expense_at=dt,
            expense_year=dt.year,
            expense_month=dt.month,
            expense_day=dt.day,
            note="",
            payload={},
            created_by=self.admin,
        )
        optional_missing = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="cash-optional-missing",
            confirmed=True,
            title="Optional by rule",
            amount=30,
            currency="UZS",
            wallet=self.wallet,
            expense_at=dt,
            expense_year=dt.year,
            expense_month=dt.month,
            expense_day=dt.day,
            note="",
            payload={},
            created_by=self.admin,
        )
        self.pt_cfg.request_not_required_rules = [
            {"field": "title", "operator": "eq", "value": "Optional by rule"}
        ]
        self.pt_cfg.save(update_fields=["request_not_required_rules"])

        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Req paid",
            amount="20.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=dt.date(),
            status=Request.STATUS_PAYED,
            expense_ref_id=required_paid.id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CASH,
            expense_id=required_paid.external_id,
            expense_year=required_paid.expense_year,
        )

        res = self.client.get("/api/cash/expenses/", **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        by_id = {row["id"]: row for row in rows}

        self.assertTrue(by_id[required_missing.id]["request_required"])
        self.assertFalse(by_id[required_missing.id]["has_paid_request"])

        self.assertTrue(by_id[required_paid.id]["request_required"])
        self.assertTrue(by_id[required_paid.id]["has_paid_request"])

        self.assertFalse(by_id[optional_missing.id]["request_required"])
        self.assertFalse(by_id[optional_missing.id]["has_paid_request"])

