from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.test_utils import list_results
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
class CashRevenueListApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="cash_rev_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        CashRevenue.objects.create(
            tenant=self.tenant,
            external_id="rev-list-1",
            total_sum=50,
            confirmed=True,
            wallet=self.wallet,
            operation="Sale",
            revenue_at=timezone.now(),
            payload={},
            created_by=self.admin,
        )

    def _headers(self):
        token = str(RefreshToken.for_user(self.admin).access_token)
        return {
            "HTTP_HOST": "acme.example.com",
            "HTTP_AUTHORIZATION": f"Bearer {token}",
        }

    def test_list_with_cursor_page_size_200(self):
        res = self.client.get("/api/cash/revenues/?page_size=200", **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        rows = list_results(res)
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("revenue_at", rows[0])


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

    def _seed_contract_expenses(self):
        dt = timezone.now()
        self.required_missing = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="cash-req-miss",
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
        self.required_paid = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="cash-req-paid",
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
        self.optional_missing = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="cash-opt-miss",
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
            expense_ref_id=self.required_paid.id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CASH,
            expense_id=self.required_paid.external_id,
            expense_year=self.required_paid.expense_year,
        )

    def test_request_highlight_contract_scenarios(self):
        self._seed_contract_expenses()
        res = self.client.get("/api/cash/expenses/", **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        by_id = {row["id"]: row for row in rows}

        self.assertTrue(by_id[self.required_missing.id]["request_required"])
        self.assertFalse(by_id[self.required_missing.id]["has_paid_request"])

        self.assertTrue(by_id[self.required_paid.id]["request_required"])
        self.assertTrue(by_id[self.required_paid.id]["has_paid_request"])

        self.assertFalse(by_id[self.optional_missing.id]["request_required"])
        self.assertFalse(by_id[self.optional_missing.id]["has_paid_request"])

    def test_missing_request_filter_returns_only_required_without_paid(self):
        self._seed_contract_expenses()
        res = self.client.get("/api/cash/expenses/?missing_request=1", **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        ids = {row["id"] for row in rows}
        self.assertIn(self.required_missing.id, ids)
        self.assertNotIn(self.required_paid.id, ids)
        self.assertNotIn(self.optional_missing.id, ids)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class CashRecordAdminEditPermissionTests(APITestCase):
    """Editing/deleting an existing cash record via API is admin-only.

    A non-admin cash role (cashier) keeps read and create access, but cannot
    PATCH or DELETE existing records — enforcement lives on the backend, not
    just in the UI (IsTenantAdminForRecordEdit).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="cash_edit_admin", password="x")
        self.cashier = User.objects.create_user(username="cash_edit_cashier", password="x")
        for u in (self.admin, self.cashier):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.cashier, role=TenantUserRole.ROLE_CASHIER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        self.host = "acme.example.com"
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        dt = timezone.now()
        self.expense = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="edit-1",
            confirmed=True,
            title="Original",
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

    def test_cashier_can_read(self):
        self.client.force_authenticate(self.cashier)
        res = self.client.get("/api/cash/expenses/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)

    def test_cashier_create_not_forbidden(self):
        # Create stays open to cash roles; permission must not block it (may 201 or 400 on payload).
        self.client.force_authenticate(self.cashier)
        res = self.client.post(
            "/api/cash/expenses/",
            {
                "external_id": "new-1",
                "title": "New",
                "amount": "5.00",
                "currency": "UZS",
                "expense_at": "2026-01-15T10:00:00",
                "confirmed": True,
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertNotEqual(res.status_code, 403, res.content)

    def test_cashier_cannot_edit(self):
        self.client.force_authenticate(self.cashier)
        res = self.client.patch(
            f"/api/cash/expenses/{self.expense.id}/",
            {"title": "Hacked"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 403, res.content)
        self.expense.refresh_from_db()
        self.assertEqual(self.expense.title, "Original")

    def test_cashier_cannot_delete(self):
        self.client.force_authenticate(self.cashier)
        res = self.client.delete(f"/api/cash/expenses/{self.expense.id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 403, res.content)
        self.assertTrue(CashExpense.objects.filter(id=self.expense.id).exists())

    def test_admin_can_edit(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(
            f"/api/cash/expenses/{self.expense.id}/",
            {"title": "Updated by admin"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.expense.refresh_from_db()
        self.assertEqual(self.expense.title, "Updated by admin")

    def test_admin_can_delete(self):
        self.client.force_authenticate(self.admin)
        res = self.client.delete(f"/api/cash/expenses/{self.expense.id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 204, res.content)
        self.assertFalse(CashExpense.objects.filter(id=self.expense.id).exists())

