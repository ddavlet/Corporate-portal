from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.requests.models import (
    Request,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.reports.models import TenantReportSettings
from apps.modules.investments.models import InvestReturn
from apps.modules.reports.cashflow_builder import (
    build_cashflow_payload_from_db,
    validate_cashflow_config_dict,
)
from apps.modules.reports.pnl_builder import (
    ReportSettingsInvalid,
    build_pnl_payload_from_db,
    compute_unassigned_payment_purposes,
    validate_pnl_config_dict,
)
from apps.modules.reports.services import (
    fetch_n8n_report_payload,
    finalize_report_payload,
    resolve_cashflow_source_for_tenant,
)
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

User = get_user_model()


def full_backend_pnl_config(**overrides):
    cfg = {
        "start_month": "2026-02",
        "cash_exclude_operations": [],
        "request_exclude_categories": [],
        "request_payment_types_for_pnl": [Request.PAYMENT_TYPE_TRANSFER],
        "payment_purpose_operational": ["Операционное назначение"],
        "payment_purpose_other": ["Прочее назначение"],
        "payment_purpose_invest_returns": ["Инвест назначение"],
        "invest_return_type_operational": ["дивиденды", "проценты"],
        "invest_return_type_other": ["доля_прибыли"],
        "invest_return_type_invest_returns": ["тело_инвестиций"],
    }
    cfg.update(overrides)
    return cfg


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

    def test_invest_returns_bucket_gets_fixed_category(self):
        raw = {
            "revenue": [],
            "operational_expenses": [
                {
                    "id": "10",
                    "amount": "40",
                    "date": "2026-04-01",
                    "category": "Проценты",
                    "purpose": "Проценты",
                }
            ],
            "other_expenses": [],
            "invest_returns": [
                {"id": "11", "amount": "15", "date": "2026-04-01", "category": "X", "purpose": "Y"},
            ],
            "metadata": {},
        }
        out = finalize_report_payload(payload_obj=raw, endpoint="/n8n/pnl-data", source="backend")
        by_id = {r["id"]: r for r in out["rows"]}
        self.assertEqual(by_id["10"]["category"], "Проценты")
        self.assertEqual(by_id["11"]["category"], "Выплаты по инвестициям")


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class BackendPnlDatabaseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="TestCo", subdomain="tstpnl")
        self.user = User.objects.create_user(username="pnl_db_u", password="x")

    def _ensure_pnl_settings(self, **cfg_overrides):
        TenantReportSettings.objects.update_or_create(
            tenant=self.tenant,
            defaults={
                "pnl_source": "backend",
                "pnl_config": full_backend_pnl_config(**cfg_overrides),
            },
        )

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
        self._ensure_pnl_settings(request_payment_types_for_pnl=[])
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

    def test_pnl_amortized_request_spreads_across_schedule_months(self):
        self._ensure_pnl_settings()
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            requester=self.user,
            title="3 months from Jan",
            description="",
            amount="300.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 15),
            amortization_months=3,
            amortization_start_date=date(2026, 1, 1),
            payment_purpose="Операционное назначение",
            status=Request.STATUS_PAYED,
        )
        payload = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        op = payload["operational_expenses"]
        self.assertEqual(len(op), 2)
        by_month = {row["date"][:7]: row["amount"] for row in op}
        self.assertEqual(by_month["2026-02"], "100.00")
        self.assertEqual(by_month["2026-03"], "100.00")

        finalized = finalize_report_payload(payload_obj=payload, endpoint="/n8n/pnl-data", source="backend")
        monthly = {row["month"]: row["expense"] for row in finalized["monthly"]}
        self.assertEqual(monthly.get("2026-02"), "100.00")
        self.assertEqual(monthly.get("2026-03"), "100.00")
        self.assertNotIn("2026-01", monthly)

    def test_pnl_amortized_request_includes_all_months_from_start_month(self):
        self._ensure_pnl_settings()
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            requester=self.user,
            title="12 months from Feb",
            description="",
            amount="1200.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 2, 1),
            amortization_months=12,
            amortization_start_date=date(2026, 2, 1),
            payment_purpose="Операционное назначение",
            status=Request.STATUS_PAYED,
        )
        payload = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        op = payload["operational_expenses"]
        self.assertEqual(len(op), 12)
        self.assertTrue(all(row["amount"] == "100.00" for row in op))
        self.assertEqual(op[0]["date"][:7], "2026-02")
        self.assertEqual(op[-1]["date"][:7], "2027-01")

    def test_pnl_long_amortization_includes_tail_after_old_billing_date(self):
        self._ensure_pnl_settings()
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            requester=self.user,
            title="36 months from 2024",
            description="",
            amount="3600.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2024, 1, 10),
            amortization_months=36,
            amortization_start_date=date(2024, 1, 1),
            payment_purpose="Операционное назначение",
            status=Request.STATUS_PAYED,
        )
        payload = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        op = payload["operational_expenses"]
        months = sorted(row["date"][:7] for row in op)
        self.assertEqual(months[0], "2026-02")
        self.assertEqual(months[-1], "2026-12")
        self.assertEqual(len(months), 11)
        self.assertTrue(all(row["amount"] == "100.00" for row in op))


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TenantReportSettingsConfigApiTests(APITestCase):
    url = "/api/reports/tenant-report-settings/"

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="pnlcfg", is_active=True)
        self.admin = User.objects.create_user(username="pnl_admin", password="x")
        self.director = User.objects.create_user(username="pnl_director", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.director, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)

    def _auth(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": "pnlcfg.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_admin_get_creates_defaults(self):
        self.assertFalse(TenantReportSettings.objects.filter(tenant=self.tenant).exists())
        res = self.client.get(self.url, **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["pnl_source"], TenantReportSettings.PNL_SOURCE_N8N)
        self.assertEqual(res.data["pnl_config"], {})
        self.assertTrue(TenantReportSettings.objects.filter(tenant=self.tenant).exists())

    def test_director_forbidden(self):
        res = self.client.get(self.url, **self._auth(self.director))
        self.assertEqual(res.status_code, 403)

    def test_admin_get_payment_purpose_pool(self):
        pool_url = "/api/reports/payment-purpose-pool/"
        res_empty = self.client.get(pool_url, **self._auth(self.admin))
        self.assertEqual(res_empty.status_code, 200, res_empty.content)
        self.assertEqual(res_empty.data.get("purposes"), [])

        rfc = RequestFormConfig.objects.create(tenant=self.tenant)
        ptc = RequestFormPaymentTypeConfig.objects.create(
            config=rfc,
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
        )
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=ptc,
            name="  Назначение из формы  ",
            is_active=True,
        )
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="r",
            description="",
            amount="10.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            payment_purpose="Только в заявках",
            status=Request.STATUS_DRAFT,
        )
        res = self.client.get(pool_url, **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        names = res.data.get("purposes") or []
        self.assertEqual(names, sorted({"Назначение из формы", "Только в заявках"}))

        res_transfer = self.client.get(
            f"{pool_url}?for_pnl_payment_types={quote(Request.PAYMENT_TYPE_TRANSFER)}",
            **self._auth(self.admin),
        )
        self.assertEqual(res_transfer.status_code, 200, res_transfer.content)
        self.assertEqual(res_transfer.data.get("purposes"), ["Назначение из формы"])

        res_cash = self.client.get(
            f"{pool_url}?for_pnl_payment_types={quote(Request.PAYMENT_TYPE_CASH)}",
            **self._auth(self.admin),
        )
        self.assertEqual(res_cash.status_code, 200, res_cash.content)
        self.assertEqual(res_cash.data.get("purposes"), ["Только в заявках"])

        res_empty_filter = self.client.get(f"{pool_url}?for_pnl_payment_types=", **self._auth(self.admin))
        self.assertEqual(res_empty_filter.status_code, 200, res_empty_filter.content)
        self.assertEqual(res_empty_filter.data.get("purposes"), [])

        res_dir = self.client.get(pool_url, **self._auth(self.director))
        self.assertEqual(res_dir.status_code, 403)

    def test_admin_patch_backend_requires_full_config(self):
        bad = self.client.patch(
            self.url,
            {"pnl_source": "backend", "pnl_config": {}},
            format="json",
            **self._auth(self.admin),
        )
        self.assertEqual(bad.status_code, 400, bad.content)

        ok = self.client.patch(
            self.url,
            {
                "pnl_source": "backend",
                "pnl_config": full_backend_pnl_config(
                    start_month="2026-02",
                    cash_exclude_operations=["x"],
                ),
            },
            format="json",
            **self._auth(self.admin),
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.data["pnl_source"], "backend")
        row = TenantReportSettings.objects.get(tenant=self.tenant)
        self.assertEqual(row.pnl_source, "backend")
        self.assertEqual(row.pnl_config["start_month"], "2026-02")

    def test_admin_get_pnl_diagnostics_unassigned_purposes(self):
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source="backend",
            pnl_config=full_backend_pnl_config(),
        )
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="r1",
            description="",
            amount="100.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            payment_purpose="Непокрытое назначение XYZ",
            status=Request.STATUS_PAYED,
        )
        res = self.client.get(f"{self.url}?pnl_diagnostics=1", **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        diag = res.data.get("pnl_diagnostics") or {}
        items = diag.get("unassigned_payment_purposes") or []
        purposes = {x["purpose"] for x in items}
        self.assertIn("Непокрытое назначение XYZ", purposes)


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class BackendCashflowSourceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("apps.modules.reports.services.resolve_cashflow_source_for_tenant", return_value="backend")
    @patch("apps.modules.reports.cashflow_builder.build_cashflow_payload_from_db")
    def test_cashflow_backend_skips_http_upstream(self, mock_build: Mock, _mock_source: Mock):
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
                endpoint="/n8n/cashflow-data",
                query_params={},
            )

        mock_get.assert_not_called()
        self.assertEqual(payload["metadata"]["source"], "backend")
        self.assertEqual(payload["totals"]["revenue"], "10")
        self.assertIn("report_settings", payload)


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class BackendCashflowDatabaseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="CashCo", subdomain="tstcf")
        self.admin = User.objects.create_user(username="cf_admin", password="x")
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            cashflow_source="backend",
            cashflow_config=full_backend_pnl_config(),
        )

    def test_request_expense_uses_cash_date_not_billing_date(self):
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="accrual only",
            description="",
            amount="1000.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 15),
            amortization_months=12,
            payment_purpose="Операционное назначение",
            status=Request.STATUS_PAYED,
            expense_year=2026,
            expense_month=3,
            expense_day=10,
        )
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="before start",
            description="",
            amount="50.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            payment_purpose="Операционное назначение",
            status=Request.STATUS_PAYED,
            expense_year=2026,
            expense_month=1,
            expense_day=1,
        )
        payload = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})
        op = payload["operational_expenses"]
        self.assertEqual(len(op), 1)
        self.assertEqual(op[0]["amount"], "1000.00")
        self.assertEqual(op[0]["date"], "2026-03-10")

    def test_pnl_amortizes_but_cashflow_does_not(self):
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="amortized",
            description="",
            amount="1200.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 2, 1),
            amortization_months=12,
            amortization_start_date=date(2026, 2, 1),
            payment_purpose="Операционное назначение",
            status=Request.STATUS_PAYED,
            expense_year=2026,
            expense_month=2,
            expense_day=1,
        )
        TenantReportSettings.objects.filter(tenant=self.tenant).update(
            pnl_source="backend",
            pnl_config=full_backend_pnl_config(),
        )
        pnl = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        cashflow = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})
        self.assertEqual(len(pnl["operational_expenses"]), 1)
        self.assertEqual(pnl["operational_expenses"][0]["amount"], "100.00")
        self.assertEqual(len(cashflow["operational_expenses"]), 1)
        self.assertEqual(cashflow["operational_expenses"][0]["amount"], "1200.00")

    def test_invest_return_uses_payout_date_not_billing_date(self):
        InvestReturn.objects.create(
            tenant=self.tenant,
            date=date(2026, 3, 15),
            billing_date=date(2026, 1, 1),
            sum=Decimal("10.00"),
            sum_uzs=Decimal("100000.00"),
            currency="UZS",
            type="дивиденды",
            recipient="инвестор",
            confirmed=True,
            created_by=self.admin,
        )
        payload = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})
        # «дивиденды» в full_backend_pnl_config попадают в operational_expenses, не в invest_returns.
        rows = payload["operational_expenses"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-03-15")

    def test_cashflow_n8n_when_source_not_backend(self):
        TenantReportSettings.objects.filter(tenant=self.tenant).update(cashflow_source="n8n")
        self.assertEqual(resolve_cashflow_source_for_tenant(tenant=self.tenant), "n8n")


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TenantCashflowReportSettingsConfigApiTests(APITestCase):
    url = "/api/reports/cashflow-report-settings/"

    def setUp(self):
        self.tenant = Tenant.objects.create(name="CfCfg", subdomain="cfcfg", is_active=True)
        self.admin = User.objects.create_user(username="cf_cfg_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)

    def _auth(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": "cfcfg.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_admin_get_creates_defaults(self):
        res = self.client.get(self.url, **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["cashflow_source"], TenantReportSettings.CASHFLOW_SOURCE_N8N)
        self.assertEqual(res.data["cashflow_config"], {})

    def test_admin_patch_backend_requires_full_config(self):
        bad = self.client.patch(
            self.url,
            {"cashflow_source": "backend", "cashflow_config": {}},
            format="json",
            **self._auth(self.admin),
        )
        self.assertEqual(bad.status_code, 400, bad.content)

        ok = self.client.patch(
            self.url,
            {"cashflow_source": "backend", "cashflow_config": full_backend_pnl_config()},
            format="json",
            **self._auth(self.admin),
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.data["cashflow_source"], "backend")


class CashflowConfigValidationTests(TestCase):
    def test_rejects_overlapping_payment_purposes(self):
        cfg = full_backend_pnl_config(
            payment_purpose_operational=["same"],
            payment_purpose_other=["same"],
        )
        with self.assertRaises(ReportSettingsInvalid):
            validate_cashflow_config_dict(cfg)


class PnlConfigValidationTests(TestCase):
    def test_rejects_overlapping_payment_purposes(self):
        cfg = full_backend_pnl_config(
            payment_purpose_operational=["same"],
            payment_purpose_other=["same"],
        )
        with self.assertRaises(ReportSettingsInvalid):
            validate_pnl_config_dict(cfg)

    def test_rejects_invalid_payment_type(self):
        cfg = full_backend_pnl_config(request_payment_types_for_pnl=["Неизвестный тип"])
        with self.assertRaises(ReportSettingsInvalid):
            validate_pnl_config_dict(cfg)

    def test_rejects_incomplete_invest_type_partition(self):
        cfg = full_backend_pnl_config(invest_return_type_invest_returns=[])
        with self.assertRaises(ReportSettingsInvalid):
            validate_pnl_config_dict(cfg)

    def test_compute_unassigned_matches_builder_scope(self):
        tenant = Tenant.objects.create(name="DiagCo", subdomain="diagpnl")
        admin = User.objects.create_user(username="diag_admin", password="x")
        TenantReportSettings.objects.create(tenant=tenant, pnl_source="backend", pnl_config=full_backend_pnl_config())
        Request.objects.create(
            tenant=tenant,
            created_by=admin,
            requester=admin,
            title="r",
            description="",
            amount="10",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            payment_purpose="Операционное назначение",
            status=Request.STATUS_PAYED,
        )
        Request.objects.create(
            tenant=tenant,
            created_by=admin,
            requester=admin,
            title="r2",
            description="",
            amount="20",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 2),
            payment_purpose="Левое назначение",
            status=Request.STATUS_PAYED,
        )
        un = compute_unassigned_payment_purposes(tenant_id=tenant.id, cfg=full_backend_pnl_config())
        self.assertTrue(any(x["purpose"] == "Левое назначение" for x in un))
        self.assertFalse(any(x["purpose"] == "Операционное назначение" for x in un))
