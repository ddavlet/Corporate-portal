from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.services import fetch_n8n_report_payload, finalize_report_payload
from apps.tenants.models import Tenant


@override_settings(
    BASE_DOMAIN="example.com",
    N8N_INTEGRATION_TOKEN="fallback-token",
    REPORTS_CACHE_TTL_SECONDS=60,
)
class ReportsCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = SimpleNamespace(subdomain="acme")

    @patch("apps.modules.reports.services.get_n8n_integration_settings")
    @patch("apps.modules.reports.services.requests.get")
    def test_fetch_payload_uses_cache_on_repeated_request(self, mock_get: Mock, mock_integration_settings: Mock):
        mock_integration_settings.return_value = SimpleNamespace(integration_token="tenant-token")
        response = Mock()
        response.json.return_value = {"revenue": [{"id": 1, "amount": "100", "date": "2026-04-01"}], "expense": []}
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        payload_1 = fetch_n8n_report_payload(
            tenant=self.tenant,
            user_id=7,
            endpoint="/n8n/cashflow-data",
            query_params={"year": "2026", "month": "04"},
        )
        payload_2 = fetch_n8n_report_payload(
            tenant=self.tenant,
            user_id=7,
            endpoint="/n8n/cashflow-data",
            query_params={"month": "04", "year": "2026"},
        )

        self.assertEqual(payload_1, payload_2)
        self.assertEqual(mock_get.call_count, 1)

    @patch("apps.modules.reports.services.get_n8n_integration_settings")
    @patch("apps.modules.reports.services.requests.get")
    def test_cache_key_isolated_by_user(self, mock_get: Mock, mock_integration_settings: Mock):
        mock_integration_settings.return_value = SimpleNamespace(integration_token="tenant-token")
        response = Mock()
        response.json.return_value = {"revenue": [], "expense": []}
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        fetch_n8n_report_payload(
            tenant=self.tenant,
            user_id=7,
            endpoint="/n8n/cashflow-data",
            query_params={},
        )
        fetch_n8n_report_payload(
            tenant=self.tenant,
            user_id=8,
            endpoint="/n8n/cashflow-data",
            query_params={},
        )

        self.assertEqual(mock_get.call_count, 2)

    @patch("apps.modules.reports.services.get_n8n_integration_settings")
    @patch("apps.modules.reports.services.requests.get")
    def test_payload_keeps_invest_returns_block(self, mock_get: Mock, mock_integration_settings: Mock):
        mock_integration_settings.return_value = SimpleNamespace(integration_token="tenant-token")
        response = Mock()
        response.json.return_value = {
            "revenue": [{"id": 1, "amount": "100", "date": "2026-04-01"}],
            "expense": [{"id": 2, "amount": "40", "date": "2026-04-01"}],
            "invest_returns": [{"id": 3, "amount": "15", "date": "2026-04-01", "category": "Инвест выплаты"}],
        }
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        payload = fetch_n8n_report_payload(
            tenant=self.tenant,
            user_id=7,
            endpoint="/n8n/pnl-data",
            query_params={},
        )

        self.assertIn("invest_returns", payload)
        self.assertEqual(len(payload["invest_returns"]), 1)
        self.assertEqual(payload["invest_returns"][0]["id"], 3)
        self.assertEqual(len(payload["rows"]), 3)
        invest_rows = [row for row in payload["rows"] if row.get("category") == "Выплаты по инвестициям"]
        self.assertEqual(len(invest_rows), 1)
        self.assertEqual(payload["totals"]["net"], "60")

    @patch("apps.modules.reports.services.get_n8n_integration_settings")
    @patch("apps.modules.reports.services.requests.get")
    def test_pnl_totals_with_operational_and_other_expenses(self, mock_get: Mock, mock_integration_settings: Mock):
        mock_integration_settings.return_value = SimpleNamespace(integration_token="tenant-token")
        response = Mock()
        response.json.return_value = {
            "revenue": [{"id": 1, "amount": "1000", "date": "2026-04-01"}],
            "operational_expenses": [{"id": 2, "amount": "300", "date": "2026-04-01"}],
            "other_expenses": [{"id": 3, "amount": "200", "date": "2026-04-01"}],
            "invest_returns": [{"id": 4, "amount": "100", "date": "2026-04-01"}],
        }
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        payload = fetch_n8n_report_payload(
            tenant=self.tenant,
            user_id=7,
            endpoint="/n8n/pnl-data",
            query_params={},
        )

        self.assertEqual(payload["totals"]["revenue"], "1000")
        self.assertEqual(payload["totals"]["operational_expense"], "300")
        self.assertEqual(payload["totals"]["other_expense"], "200")
        self.assertEqual(payload["totals"]["ebit"], "700")
        self.assertEqual(payload["totals"]["net"], "500")
        self.assertEqual(payload["totals"]["invest_returns"], "100")
        self.assertEqual(payload["totals"]["balance"], "400")


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class BackendPnlSourceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("apps.modules.reports.services.resolve_pnl_source_for_tenant", return_value="backend")
    @patch("apps.modules.reports.pnl_builder.build_pnl_payload_from_db")
    def test_pnl_backend_skips_http_upstream(self, mock_build: Mock, _mock_source: Mock):
        mock_build.return_value = {
            "revenue": [{"id": "1", "amount": "10", "date": "2026-04-01", "category": "X"}],
            "operational_expenses": [],
            "other_expenses": [],
            "invest_returns": [],
            "metadata": {"start_month": "2026-02"},
            "report_settings": {"start_month": "2026-02"},
        }
        tenant = SimpleNamespace(subdomain="acme")

        with patch("apps.modules.reports.services.requests.get") as mock_get:
            payload = fetch_n8n_report_payload(
                tenant=tenant,
                user_id=3,
                endpoint="/n8n/pnl-data",
                query_params={},
            )

        mock_get.assert_not_called()
        self.assertEqual(payload["metadata"]["source"], "backend")
        self.assertEqual(payload["totals"]["revenue"], "10")
        self.assertIn("report_settings", payload)


class FinalizeReportPayloadTests(SimpleTestCase):
    def test_passes_through_report_settings(self):
        raw = {
            "revenue": [],
            "operational_expenses": [],
            "other_expenses": [],
            "invest_returns": [],
            "metadata": {"start_month": "2026-02"},
            "report_settings": {"start_month": "2026-02", "cash_exclude_operations": ["a"]},
        }
        out = finalize_report_payload(payload_obj=raw, endpoint="/n8n/pnl-data", source="backend")
        self.assertEqual(out["report_settings"]["cash_exclude_operations"], ["a"])


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class BackendPnlDatabaseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="TestCo", subdomain="tstpnl")

    def test_missing_tenant_report_settings_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            fetch_n8n_report_payload(
                tenant=self.tenant,
                user_id=1,
                endpoint="/n8n/pnl-data",
                query_params={},
            )
        self.assertIn("tenant_report_settings", str(ctx.exception).lower())

    def test_backend_pnl_returns_empty_blocks_with_config(self):
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source="backend",
            pnl_config={
                "start_month": "2026-02",
                "cash_exclude_operations": [],
                "request_exclude_categories": [],
                "income_tax_payment_purpose": "Подоходный налог",
                "invest_return_exclude_types": [],
            },
        )
        payload = fetch_n8n_report_payload(
            tenant=self.tenant,
            user_id=1,
            endpoint="/n8n/pnl-data",
            query_params={},
        )
        self.assertEqual(payload["metadata"]["source"], "backend")
        self.assertEqual(payload["metadata"]["start_month"], "2026-02")
        self.assertEqual(payload["revenue"], [])
        self.assertIn("report_settings", payload)
