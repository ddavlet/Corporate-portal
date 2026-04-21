from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.budgets.models import Budget
from apps.modules.budgets.serializers import _period_date_range
from apps.modules.requests.models import Request, RequestCategory

User = get_user_model()


class BudgetModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="buser", password="x")
        self.category = RequestCategory.objects.create(tenant=self.tenant, name="IT", is_active=True)

    def test_create_budget(self):
        b = Budget.objects.create(
            tenant=self.tenant,
            name="IT Monthly",
            category=self.category,
            period_type=Budget.PERIOD_MONTHLY,
            limit_amount=Decimal("1000000"),
            currency="UZS",
            created_by=self.user,
        )
        self.assertIsNotNone(b.pk)
        self.assertTrue(b.is_active)

    def test_str(self):
        b = Budget.objects.create(
            tenant=self.tenant,
            name="IT Monthly",
            category=self.category,
            period_type=Budget.PERIOD_MONTHLY,
            limit_amount=Decimal("500000"),
            currency="UZS",
            created_by=self.user,
        )
        self.assertIn("IT Monthly", str(b))
        self.assertIn("Acme", str(b))


class PeriodDateRangeTests(TestCase):
    def test_monthly_jan(self):
        start, end = _period_date_range(Budget.PERIOD_MONTHLY, 2026, 1)
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 2, 1))

    def test_monthly_dec(self):
        start, end = _period_date_range(Budget.PERIOD_MONTHLY, 2026, 12)
        self.assertEqual(start, date(2026, 12, 1))
        self.assertEqual(end, date(2027, 1, 1))

    def test_quarterly_month_1_maps_to_q1(self):
        start, end = _period_date_range(Budget.PERIOD_QUARTERLY, 2026, 1)
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 4, 1))

    def test_quarterly_month_3_maps_to_q1(self):
        start, end = _period_date_range(Budget.PERIOD_QUARTERLY, 2026, 3)
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 4, 1))

    def test_quarterly_month_4_maps_to_q2(self):
        start, end = _period_date_range(Budget.PERIOD_QUARTERLY, 2026, 4)
        self.assertEqual(start, date(2026, 4, 1))
        self.assertEqual(end, date(2026, 7, 1))

    def test_quarterly_month_10_maps_to_q4(self):
        start, end = _period_date_range(Budget.PERIOD_QUARTERLY, 2026, 10)
        self.assertEqual(start, date(2026, 10, 1))
        self.assertEqual(end, date(2027, 1, 1))

    def test_yearly(self):
        start, end = _period_date_range(Budget.PERIOD_YEARLY, 2026, 7)
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2027, 1, 1))


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class BudgetApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

        self.admin = User.objects.create_user(username="badmin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="budgets", is_enabled=True)

        self.director = User.objects.create_user(username="bdir", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.director, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)

        self.accountant = User.objects.create_user(username="bacc", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.accountant, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.accountant, role=TenantUserRole.ROLE_ACCOUNTANT)

        self.category = RequestCategory.objects.create(tenant=self.tenant, name="IT", is_active=True)

        self.budget = Budget.objects.create(
            tenant=self.tenant,
            name="IT Q1",
            category=self.category,
            period_type=Budget.PERIOD_MONTHLY,
            limit_amount=Decimal("2000000"),
            currency="UZS",
            created_by=self.admin,
        )

    def _headers(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": "acme.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_admin_can_list(self):
        resp = self.client.get("/api/budgets/", **self._headers(self.admin))
        self.assertEqual(resp.status_code, 200)

    def test_director_can_list(self):
        resp = self.client.get("/api/budgets/", **self._headers(self.director))
        self.assertEqual(resp.status_code, 200)

    def test_accountant_denied(self):
        resp = self.client.get("/api/budgets/", **self._headers(self.accountant))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_create(self):
        payload = {
            "name": "Marketing",
            "category": self.category.pk,
            "period_type": Budget.PERIOD_MONTHLY,
            "limit_amount": "500000.00",
            "currency": "UZS",
            "is_active": True,
        }
        resp = self.client.post("/api/budgets/", payload, format="json", **self._headers(self.admin))
        self.assertEqual(resp.status_code, 201)

    def test_director_can_create(self):
        payload = {
            "name": "HR Budget",
            "category": self.category.pk,
            "period_type": Budget.PERIOD_QUARTERLY,
            "limit_amount": "1000000.00",
            "currency": "USD",
            "is_active": True,
        }
        resp = self.client.post("/api/budgets/", payload, format="json", **self._headers(self.director))
        self.assertEqual(resp.status_code, 201)

    def test_categories_endpoint(self):
        resp = self.client.get("/api/budgets/categories/", **self._headers(self.admin))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(any(c["name"] == "IT" for c in data))

    def test_spend_detail_endpoint(self):
        resp = self.client.get(
            f"/api/budgets/{self.budget.pk}/spend-detail/?year=2026&period=1",
            **self._headers(self.admin),
        )
        self.assertEqual(resp.status_code, 200)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class BudgetSpendComputeTests(APITestCase):
    """Verify that spent_amount and utilization_pct reflect matching Requests."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="SpendCo", subdomain="spendco", is_active=True)
        self.admin = User.objects.create_user(username="sadmin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="budgets", is_enabled=True)

        self.category = RequestCategory.objects.create(tenant=self.tenant, name="Office", is_active=True)
        self.budget = Budget.objects.create(
            tenant=self.tenant,
            name="Office Jan",
            category=self.category,
            period_type=Budget.PERIOD_MONTHLY,
            limit_amount=Decimal("1000000"),
            currency="UZS",
            created_by=self.admin,
        )

        def _make_request(billing_date, amount, status=Request.STATUS_APPROVED):
            return Request.objects.create(
                tenant=self.tenant,
                created_by=self.admin,
                category="Office",
                amount=amount,
                currency="UZS",
                status=status,
                billing_date=billing_date,
                requester=self.admin,
            )

        self.req_in = _make_request(date(2026, 1, 15), Decimal("300000"))
        self.req_out = _make_request(date(2026, 2, 5), Decimal("200000"))
        self.req_wrong_currency = _make_request(date(2026, 1, 20), Decimal("100000"))
        self.req_wrong_currency.currency = "USD"
        self.req_wrong_currency.save(update_fields=["currency"])
        self.req_draft = _make_request(date(2026, 1, 10), Decimal("50000"), status=Request.STATUS_DRAFT if hasattr(Request, 'STATUS_DRAFT') else "DRAFT")

    def _headers(self):
        token = str(RefreshToken.for_user(self.admin).access_token)
        return {"HTTP_HOST": "spendco.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_spent_amount_only_counts_matching_requests(self):
        resp = self.client.get(
            f"/api/budgets/{self.budget.pk}/spend-detail/?year=2026&period=1",
            **self._headers(),
        )
        self.assertEqual(resp.status_code, 200)

    def test_list_utilization_reflects_spend(self):
        resp = self.client.get("/api/budgets/?year=2026&period=1", **self._headers())
        self.assertEqual(resp.status_code, 200)
        results = resp.json()
        budget_data = next(b for b in results if b["id"] == self.budget.pk)
        self.assertEqual(Decimal(budget_data["spent_amount"]), Decimal("300000"))
        self.assertGreater(float(budget_data["utilization_pct"]), 0)
