from datetime import date

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.tests import full_backend_pnl_config
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

User = get_user_model()
PNL = "/api/reports/rules/pnl/"
CASHFLOW = "/api/reports/rules/cashflow/"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ReportRulesApiTests(APITestCase):
    """Each report keeps its own source and rules; one API edits either of them."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Rules", subdomain="rulesapi", is_active=True)
        self.admin = self._member("rules_admin", TenantUserRole.ROLE_ADMIN)
        self.director = self._member("rules_director", TenantUserRole.ROLE_DIRECTOR)

    def _member(self, username, role):
        user = User.objects.create_user(username=username, password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def _auth(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": "rulesapi.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_get_creates_defaults_for_each_report(self):
        for url, report in ((PNL, "pnl"), (CASHFLOW, "cashflow")):
            res = self.client.get(url, **self._auth(self.admin))
            self.assertEqual(res.status_code, 200, res.content)
            self.assertEqual((res.data["report"], res.data["source"], res.data["rules"]), (report, "n8n", {}))
            self.assertNotIn("diagnostics", res.data)
        self.assertTrue(TenantReportSettings.objects.filter(tenant=self.tenant).exists())

    def test_only_admins(self):
        self.assertEqual(self.client.get(PNL, **self._auth(self.director)).status_code, 403)
        res = self.client.patch(CASHFLOW, {"source": "n8n"}, format="json", **self._auth(self.director))
        self.assertEqual(res.status_code, 403)

    def test_unknown_report_is_404(self):
        res = self.client.get("/api/reports/rules/ghost/", **self._auth(self.admin))
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.data["detail"], "Отчёт «ghost» не найден.")
        res = self.client.patch("/api/reports/rules/ghost/", {}, format="json", **self._auth(self.admin))
        self.assertEqual(res.status_code, 404)

    def test_backend_rules_are_validated_and_saved_to_the_reports_own_field(self):
        bad = self.client.patch(CASHFLOW, {"source": "backend", "rules": {}}, format="json", **self._auth(self.admin))
        self.assertEqual(bad.status_code, 400, bad.content)
        self.assertIn("rules", bad.data)
        rules = full_backend_pnl_config(opening_balance="250")
        ok = self.client.patch(CASHFLOW, {"source": "backend", "rules": rules}, format="json", **self._auth(self.admin))
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual((ok.data["source"], ok.data["rules"]), ("backend", rules))
        row = TenantReportSettings.objects.get(tenant=self.tenant)
        self.assertEqual((row.cashflow_source, row.cashflow_config), ("backend", rules))
        self.assertEqual((row.pnl_source, row.pnl_config), ("n8n", {}))

    def test_n8n_source_saves_rules_without_validation(self):
        res = self.client.patch(PNL, {"source": "n8n", "rules": {"start_month": "later"}}, format="json", **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(TenantReportSettings.objects.get(tenant=self.tenant).pnl_config, {"start_month": "later"})

    def test_null_rules_clear_them(self):
        TenantReportSettings.objects.create(tenant=self.tenant, pnl_config=full_backend_pnl_config())
        res = self.client.patch(PNL, {"rules": None}, format="json", **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["rules"], {})

    def test_rejects_an_unknown_source_and_rules_that_are_not_an_object(self):
        self.assertEqual(self.client.patch(PNL, {"source": "excel"}, format="json", **self._auth(self.admin)).status_code, 400)
        self.assertEqual(self.client.patch(PNL, {"rules": ["x"]}, format="json", **self._auth(self.admin)).status_code, 400)

    def test_diagnostics_use_the_reports_own_rules(self):
        # «Аренда» has a section in the PnL rules but not in the Cashflow rules.
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source="backend",
            pnl_config=full_backend_pnl_config(payment_purpose_operational=["Операционное назначение", "Аренда"]),
            cashflow_source="backend",
            cashflow_config=full_backend_pnl_config(),
        )
        Request.objects.create(
            tenant=self.tenant, created_by=self.admin, requester=self.admin, title="rent", description="",
            amount="70.00", currency="UZS", payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL, billing_date=date(2026, 3, 1), payment_purpose="Аренда",
            status=Request.STATUS_PAYED, expense_year=2026, expense_month=3, expense_day=5,
        )
        pnl = self.client.get(f"{PNL}?diagnostics=1", **self._auth(self.admin)).data["diagnostics"]
        cashflow = self.client.get(f"{CASHFLOW}?diagnostics=1", **self._auth(self.admin)).data["diagnostics"]
        self.assertEqual(pnl, {"unassigned_payment_purposes": []})
        self.assertEqual(
            cashflow, {"unassigned_payment_purposes": [{"purpose": "Аренда", "count": 1, "amount": "70.00"}]}
        )

    def test_diagnostics_explain_rules_that_cannot_be_used(self):
        res = self.client.get(f"{CASHFLOW}?diagnostics=1", **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("error", res.data["diagnostics"])

    def test_old_settings_endpoints_are_gone(self):
        for url in ("/api/reports/tenant-report-settings/", "/api/reports/cashflow-report-settings/"):
            self.assertEqual(self.client.get(url, **self._auth(self.admin)).status_code, 404, url)
