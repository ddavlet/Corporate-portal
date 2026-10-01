from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.pnl_builder import build_pnl_payload_from_db
from apps.modules.reports.services import fetch_report_payload, save_report_rules
from apps.modules.reports.tests import full_backend_pnl_config
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()
STATEMENT = "/api/reports/statement/"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"], REPORTS_CACHE_TTL_SECONDS=60)
class ReportsLoadIndependentlyTests(APITestCase):
    """Each report reads only its own source and rules: broken rules of one never break the other."""

    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Independent", subdomain="indep", is_active=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="reports", is_enabled=True)
        self.director = User.objects.create_user(username="indep_director", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.director, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)

    def _get(self, url, params=None):
        token = str(RefreshToken.for_user(self.director).access_token)
        return self.client.get(url, params or {}, HTTP_HOST="indep.example.com", HTTP_AUTHORIZATION=f"Bearer {token}")

    def _settings(self, *, pnl_config, cashflow_config):
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source="backend",
            pnl_config=pnl_config,
            cashflow_source="backend",
            cashflow_config=cashflow_config,
        )

    def test_cashflow_opens_while_the_pnl_rules_are_broken(self):
        self._settings(pnl_config={}, cashflow_config=full_backend_pnl_config())
        self.assertEqual(self._get("/api/reports/cashflow/").status_code, 200)
        statement = self._get(STATEMENT, {"template": "professional", "report": "cashflow"})
        self.assertEqual(statement.status_code, 200, statement.content[:300])
        self.assertEqual(self._get("/api/reports/pnl/").status_code, 503)

    def test_pnl_opens_while_the_cashflow_rules_are_broken(self):
        self._settings(pnl_config=full_backend_pnl_config(), cashflow_config={})
        self.assertEqual(self._get("/api/reports/pnl/").status_code, 200)
        statement = self._get(STATEMENT, {"template": "professional", "report": "pnl"})
        self.assertEqual(statement.status_code, 200, statement.content[:300])
        self.assertEqual(self._get("/api/reports/cashflow/").status_code, 503)

    def test_pnl_data_for_n8n_is_built_from_the_pnl_rules(self):
        self._settings(pnl_config=full_backend_pnl_config(), cashflow_config={})
        res = self._get("/api/pnl-data/")
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res.data["metadata"]["source"], "backend")


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class ReportCacheFollowsRulesTests(TestCase):
    """The payload cache lasts a minute, but saved rules show at once."""

    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Cached", subdomain="cachedrules")
        self.user = User.objects.create_user(username="cached_rules_u", password="x")
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source="backend",
            pnl_config=full_backend_pnl_config(payment_purpose_operational=["Операционное назначение", "Аренда"]),
        )
        Request.objects.create(
            tenant=self.tenant, created_by=self.user, requester=self.user, title="rent", description="",
            amount="90.00", currency="UZS", payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL, billing_date=date(2026, 3, 1), payment_purpose="Аренда",
            status=Request.STATUS_PAYED,
        )

    def _load(self):
        return fetch_report_payload(tenant=self.tenant, user_id=self.user.id, report="pnl", query_params={})

    def test_unchanged_rules_come_from_the_cache(self):
        with patch("apps.modules.reports.pnl_builder.build_pnl_payload_from_db", wraps=build_pnl_payload_from_db) as build:
            self._load()
            self._load()
        self.assertEqual(build.call_count, 1)

    def test_saved_rules_rebuild_the_report_at_once(self):
        self.assertEqual(len(self._load()["operational_expenses"]), 1)
        save_report_rules(
            tenant=self.tenant,
            report="pnl",
            rules=full_backend_pnl_config(payment_purpose_other=["Прочее назначение", "Аренда"]),
        )
        payload = self._load()
        self.assertEqual((len(payload["operational_expenses"]), len(payload["other_expenses"])), (0, 1))

    @patch("apps.modules.reports.services.get_n8n_integration_settings")
    @patch("apps.modules.reports.services.requests.get")
    def test_n8n_reports_do_not_depend_on_saved_rules(self, mock_get: Mock, mock_integration_settings: Mock):
        TenantReportSettings.objects.filter(tenant=self.tenant).update(pnl_source="n8n")
        mock_integration_settings.return_value = SimpleNamespace(integration_token="tenant-token")
        response = Mock()
        response.json.return_value = {"revenue": [], "expense": []}
        response.raise_for_status.return_value = None
        mock_get.return_value = response
        self._load()
        TenantReportSettings.objects.filter(tenant=self.tenant).update(pnl_config={})
        self._load()
        self.assertEqual(mock_get.call_count, 1)
