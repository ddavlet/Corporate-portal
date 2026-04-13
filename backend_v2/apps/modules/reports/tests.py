from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.modules.reports.services import fetch_n8n_report_payload


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
