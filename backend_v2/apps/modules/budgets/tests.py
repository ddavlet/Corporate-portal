from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.test_utils import list_results
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
        self.req_draft = _make_request(date(2026, 1, 10), Decimal("50000"), status=Request.STATUS_DRAFT)

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
        budget_data = next(b for b in list_results(resp) if b["id"] == self.budget.pk)
        self.assertEqual(Decimal(budget_data["spent_amount"]), Decimal("300000"))
        self.assertGreater(float(budget_data["utilization_pct"]), 0)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class BudgetByPaymentPurposeTests(APITestCase):
    """Budgets could only be set on a request category; a budget on a payment purpose
    (назначение платежа) counts requests with that purpose whatever their category."""

    def setUp(self):
        from apps.modules.requests.models import (
            RequestFormConfig,
            RequestFormPaymentTypeConfig,
            RequestPaymentPurposeConfig,
        )

        self.tenant = Tenant.objects.create(name="PurposeCo", subdomain="purposeco", is_active=True)
        self.admin = User.objects.create_user(username="padmin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="budgets", is_enabled=True)
        self.category = RequestCategory.objects.create(tenant=self.tenant, name="Office", is_active=True)

        ptc = RequestFormPaymentTypeConfig.objects.create(
            config=RequestFormConfig.objects.create(tenant=self.tenant),
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
        )
        RequestPaymentPurposeConfig.objects.create(payment_type_config=ptc, name="Аренда", category="Office")
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=ptc, name="Старое", category="Office", is_active=False
        )

        def _make(purpose, amount, *, category="Office", currency="UZS", status=Request.STATUS_PAYED,
                  billing=date(2026, 3, 10)):
            return Request.objects.create(
                tenant=self.tenant, created_by=self.admin, requester=self.admin, category=category,
                payment_purpose=purpose, amount=Decimal(amount), currency=currency, status=status,
                billing_date=billing,
            )

        self.rent = _make("Аренда", "700")
        self.rent_other_category = _make("Аренда", "100", category="Прочее", status=Request.STATUS_APPROVED)
        self.rent_usd = _make("Аренда", "5", currency="USD")
        self.rent_april = _make("Аренда", "900", billing=date(2026, 4, 1))
        self.rent_draft = _make("Аренда", "999", status=Request.STATUS_DRAFT)
        self.water = _make("Вода", "50")

        self.budget = Budget.objects.create(
            tenant=self.tenant, name="Аренда / мес", payment_purpose="Аренда",
            period_type=Budget.PERIOD_MONTHLY, limit_amount=Decimal("1000"), currency="UZS",
            created_by=self.admin,
        )

    def _headers(self):
        token = str(RefreshToken.for_user(self.admin).access_token)
        return {"HTTP_HOST": "purposeco.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _payload(self, **kw):
        payload = {"name": "Новый", "period_type": Budget.PERIOD_MONTHLY, "limit_amount": "100.00", "currency": "UZS"}
        payload.update(kw)
        return payload

    def test_spend_counts_requests_with_the_purpose_in_any_category(self):
        resp = self.client.get("/api/budgets/?year=2026&period=3", **self._headers())
        self.assertEqual(resp.status_code, 200)
        row = next(b for b in list_results(resp) if b["id"] == self.budget.pk)
        self.assertEqual(Decimal(row["spent_amount"]), Decimal("800"))
        self.assertEqual(row["payment_purpose"], "Аренда")
        self.assertIsNone(row["category"])
        self.assertIsNone(row["category_name"])

        resp = self.client.get(f"/api/budgets/{self.budget.pk}/spend-detail/?year=2026&period=3", **self._headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            {r["id"] for r in resp.json()["results"]}, {self.rent.id, self.rent_other_category.id}
        )

    def test_create_by_purpose_strips_and_stores_no_category(self):
        resp = self.client.post(
            "/api/budgets/", self._payload(payment_purpose="  Вода "), format="json", **self._headers()
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        budget = Budget.objects.get(pk=resp.json()["id"])
        self.assertEqual(budget.payment_purpose, "Вода")
        self.assertIsNone(budget.category_id)

    def test_create_requires_exactly_one_of_category_and_purpose(self):
        both = self._payload(category=self.category.pk, payment_purpose="Вода")
        neither = self._payload(name="Пустой")
        for payload in (both, neither):
            resp = self.client.post("/api/budgets/", payload, format="json", **self._headers())
            self.assertEqual(resp.status_code, 400, payload)

    def test_category_budget_can_be_switched_to_purpose(self):
        budget = Budget.objects.create(
            tenant=self.tenant, name="Office", category=self.category, period_type=Budget.PERIOD_MONTHLY,
            limit_amount=Decimal("100"), currency="UZS",
        )
        resp = self.client.patch(
            f"/api/budgets/{budget.pk}/", {"category": None, "payment_purpose": "Вода"},
            format="json", **self._headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        budget.refresh_from_db()
        self.assertIsNone(budget.category_id)
        self.assertEqual(budget.payment_purpose, "Вода")

        resp = self.client.patch(
            f"/api/budgets/{budget.pk}/", {"payment_purpose": "Аренда"}, format="json", **self._headers()
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_filter_by_purpose(self):
        Budget.objects.create(
            tenant=self.tenant, name="Office", category=self.category, period_type=Budget.PERIOD_MONTHLY,
            limit_amount=Decimal("100"), currency="UZS",
        )
        resp = self.client.get("/api/budgets/?payment_purpose=Аренда", **self._headers())
        self.assertEqual([b["id"] for b in list_results(resp)], [self.budget.pk])

    def test_payment_purposes_endpoint_merges_config_and_used(self):
        resp = self.client.get("/api/budgets/payment-purposes/", **self._headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            [{"name": "Аренда", "category": "Office"}, {"name": "Вода", "category": ""}],
        )
