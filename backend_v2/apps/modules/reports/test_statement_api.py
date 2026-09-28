from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from openpyxl import load_workbook
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.test_fixtures import TODAY, sample_payload
from apps.modules.reports.xlsx_export import XLSX_CONTENT_TYPE
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()
FETCH = "apps.modules.reports.services.fetch_n8n_report_payload"
STATEMENT = "/api/reports/statement/"
LINES = "/api/reports/statement/lines/"
TEMPLATES = "/api/reports/templates/"
EXPORT = "/api/reports/statement/export/"
LINES_EXPORT = "/api/reports/statement/lines/export/"
VENDORS = "/api/reports/statement/vendors/"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"], TIME_ZONE="Asia/Tashkent")
@patch("django.utils.timezone.localdate", return_value=TODAY)
class StatementApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Демо Трейд", subdomain="stmt", is_active=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="reports", is_enabled=True)
        self.admin = self._member("stmt_admin", TenantUserRole.ROLE_ADMIN)
        self.director = self._member("stmt_director", TenantUserRole.ROLE_DIRECTOR)
        self.accountant = self._member("stmt_accountant", TenantUserRole.ROLE_ACCOUNTANT)

    def _member(self, username, role):
        user = User.objects.create_user(username=username, password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def _auth(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": "stmt.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    # templates
    def test_templates_default_for_tenant_without_settings(self, _today):
        res = self.client.get(TEMPLATES, **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["default"], "classic")
        self.assertEqual([t["key"] for t in res.data["allowed"]], ["classic", "professional"])
        self.assertEqual([t["key"] for t in res.data["available"]], ["classic", "professional"])

    def test_templates_patch_is_admin_only(self, _today):
        body = {"default_template": "professional", "allowed_templates": ["professional"]}
        self.assertEqual(self.client.patch(TEMPLATES, body, format="json", **self._auth(self.director)).status_code, 403)
        res = self.client.patch(TEMPLATES, body, format="json", **self._auth(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        row = TenantReportSettings.objects.get(tenant=self.tenant)
        self.assertEqual((row.default_template, row.allowed_templates), ("professional", ["professional"]))

    def test_templates_patch_rejects_invalid_settings(self, _today):
        bad_default = {"default_template": "professional", "allowed_templates": ["classic"]}
        unknown = {"default_template": "classic", "allowed_templates": ["classic", "ghost"]}
        self.assertEqual(self.client.patch(TEMPLATES, bad_default, format="json", **self._auth(self.admin)).status_code, 400)
        self.assertEqual(self.client.patch(TEMPLATES, unknown, format="json", **self._auth(self.admin)).status_code, 400)

    # statement
    def test_statement_returns_professional_pnl(self, _today):
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(
                STATEMENT,
                {"template": "professional", "report": "pnl", "period": "ytd", "compare": "yoy"},
                **self._auth(self.director),
            )
        self.assertEqual(res.status_code, 200, res.content)
        rev = next(row for row in res.data["rows"] if row["id"] == "rev")
        self.assertEqual(rev["values"]["total"], "3500.00")
        self.assertEqual([c["key"] for c in res.data["columns"]][-3:], ["total", "compare", "delta"])
        self.assertEqual(res.data["template"], "professional")
        self.assertEqual(res.data["meta"]["company"], "Демо Трейд")
        self.assertEqual(res.data["meta"]["period_label"], "янв – 23 сен 2026")
        self.assertEqual(res.data["warnings"], [])
        self.assertTrue(any(rule["label"] == "Период отчёта" for rule in res.data["methodology"]))

    def test_statement_rejects_classic_template(self, _today):
        res = self.client.get(STATEMENT, {"template": "classic", "report": "pnl"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 400)

    def test_statement_forbidden_when_template_not_allowed(self, _today):
        TenantReportSettings.objects.create(tenant=self.tenant, default_template="classic", allowed_templates=["classic"])
        res = self.client.get(STATEMENT, {"template": "professional", "report": "pnl"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 403)

    def test_statement_requires_reports_role(self, _today):
        res = self.client.get(STATEMENT, {"template": "professional", "report": "pnl"}, **self._auth(self.accountant))
        self.assertEqual(res.status_code, 403)

    def test_statement_rejects_months_before_2000(self, _today):
        params = {"template": "professional", "report": "pnl", "period": "month", "month": "0001-01"}
        res = self.client.get(STATEMENT, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 400)
        self.assertIn("month", res.data)

    def test_statement_survives_a_malformed_start_month_from_the_source(self, _today):
        payload = sample_payload()
        payload["metadata"]["start_month"] = "2024-13"
        payload["report_settings"]["start_month"] = "2024-13"
        with patch(FETCH, return_value=payload):
            res = self.client.get(STATEMENT, {"template": "professional", "report": "pnl"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res.data["meta"]["start_month"], "2025-08")  # earliest operation month instead

    def test_statement_names_an_unknown_template(self, _today):
        res = self.client.get(STATEMENT, {"template": "ghost", "report": "pnl"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["detail"], "Шаблон «ghost» не найден.")

    def test_lines_reject_a_line_the_report_does_not_have(self, _today):
        auth = self._auth(self.director)
        for line in ("ebit", "opex.deadbeef"):
            params = {"template": "professional", "report": "pnl", "line": line, "from": "2026-08-01", "to": "2026-08-31"}
            with patch(FETCH, return_value=sample_payload()):
                self.assertEqual(self.client.get(LINES, params, **auth).status_code, 404, line)
                self.assertEqual(self.client.get(LINES_EXPORT, params, **auth).status_code, 404, line)

    def test_statement_validates_period_params(self, _today):
        auth = self._auth(self.director)
        year_without_year = {"template": "professional", "report": "pnl", "period": "year"}
        future_month = {"template": "professional", "report": "pnl", "period": "month", "month": "2026-10"}
        self.assertEqual(self.client.get(STATEMENT, year_without_year, **auth).status_code, 400)
        self.assertEqual(self.client.get(STATEMENT, future_month, **auth).status_code, 400)

    def test_statement_warnings_only_for_admin(self, _today):
        unassigned = [{"purpose": "Аренда техники", "count": 3, "amount": "42600000.00"}]
        params = {"template": "professional", "report": "pnl"}
        with patch(FETCH, return_value=sample_payload()), patch(
            "apps.modules.reports.pnl_builder.compute_unassigned_payment_purposes", return_value=unassigned
        ):
            admin_res = self.client.get(STATEMENT, params, **self._auth(self.admin))
            director_res = self.client.get(STATEMENT, params, **self._auth(self.director))
        self.assertEqual(
            admin_res.data["warnings"],
            [{"code": "unassigned_purposes", "count": 3, "amount": "42600000.00", "purposes": ["Аренда техники"]}],
        )
        self.assertEqual(director_res.data["warnings"], [])

    def test_statement_upstream_failure_is_503(self, _today):
        with patch(FETCH, side_effect=RuntimeError("No tenant_report_settings for tenant_id=1")):
            res = self.client.get(STATEMENT, {"template": "professional", "report": "pnl"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 503)
        self.assertIn("tenant_report_settings", res.data["detail"])

    # lines
    def test_lines_total_matches_statement_cell(self, _today):
        auth = self._auth(self.director)
        with patch(FETCH, return_value=sample_payload()):
            statement = self.client.get(STATEMENT, {"template": "professional", "report": "pnl"}, **auth)
            lines = self.client.get(
                LINES,
                {"template": "professional", "report": "pnl", "line": "rev", "from": "2026-08-01", "to": "2026-08-31"},
                **auth,
            )
        rev = next(row for row in statement.data["rows"] if row["id"] == "rev")
        self.assertEqual(lines.status_code, 200, lines.content)
        self.assertEqual(lines.data["total"], rev["values"]["2026-08"])
        self.assertEqual(lines.data["count"], 2)

    def test_lines_search_and_paging(self, _today):
        params = {
            "template": "professional", "report": "pnl", "line": "opex", "from": "2026-01-01",
            "to": "2026-09-23", "q": "выставка", "page_size": 2,
        }
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(LINES, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.data["count"], res.data["total"], len(res.data["items"])), (3, "300.00", 2))
        self.assertEqual(res.data["items"][0]["amortization"], {"index": 3, "count": 3})
        self.assertEqual(res.data["items"][0]["line_label"], "Маркетинг")

    def test_lines_rejects_reversed_range(self, _today):
        params = {"template": "professional", "report": "pnl", "line": "rev", "from": "2026-09-01", "to": "2026-08-01"}
        res = self.client.get(LINES, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 400)

    def test_lines_without_line_list_every_section(self, _today):
        params = {"template": "professional", "report": "pnl", "from": "2026-08-01", "to": "2026-08-31"}
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(LINES, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.data["line"], res.data["count"], res.data["total"]), ("", 6, "2270.00"))
        # Money in = bank 1500 + cash 300; money out = rent 200 + marketing 100 + taxes 50 + investor payout 120.
        self.assertEqual((res.data["total_in"], res.data["total_out"]), ("1800.00", "470.00"))

    def test_lines_filter_by_source(self, _today):
        params = {"template": "professional", "report": "pnl", "from": "2026-08-01", "to": "2026-08-31", "source": "bank"}
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(LINES, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.data["count"], res.data["total"]), (1, "1500.00"))

    def test_lines_rejects_unknown_source(self, _today):
        params = {"template": "professional", "report": "pnl", "from": "2026-08-01", "to": "2026-08-31", "source": "ghost"}
        res = self.client.get(LINES, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 400)

    # exports
    def test_export_returns_the_statement_workbook(self, _today):
        params = {"template": "professional", "report": "pnl", "period": "ytd", "compare": "yoy", "units": "k"}
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(EXPORT, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Type"], XLSX_CONTENT_TYPE)
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="PnL_2026-YTD_stmt_2026-09-23.xlsx"')
        workbook = load_workbook(BytesIO(res.content))
        self.assertEqual(workbook.sheetnames, ["Отчёт", "Операции", "Параметры"])
        report = workbook["Отчёт"]
        self.assertEqual((report["A1"].value, report["A5"].value), ("Демо Трейд", "Единицы: тыс. сум"))
        self.assertTrue(report["A6"].value.endswith("· stmt_director"))
        # Header + the 10 operations of 1 Jan – 23 Sep 2026 across revenue, opex, other and investor payouts.
        self.assertEqual(workbook["Операции"].max_row, 11)

    def test_export_validates_units(self, _today):
        res = self.client.get(EXPORT, {"template": "professional", "report": "pnl", "units": "bn"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 400)

    def test_export_respects_allowed_templates(self, _today):
        TenantReportSettings.objects.create(tenant=self.tenant, default_template="classic", allowed_templates=["classic"])
        res = self.client.get(EXPORT, {"template": "professional", "report": "pnl"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 403)

    def test_export_upstream_failure_is_503(self, _today):
        with patch(FETCH, side_effect=RuntimeError("No tenant_report_settings for tenant_id=1")):
            res = self.client.get(EXPORT, {"template": "professional", "report": "pnl"}, **self._auth(self.director))
        self.assertEqual(res.status_code, 503)

    def test_lines_export_returns_the_cell_operations(self, _today):
        params = {"template": "professional", "report": "pnl", "line": "rev", "from": "2026-08-01", "to": "2026-08-31"}
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(LINES_EXPORT, params, **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(
            res["Content-Disposition"], 'attachment; filename="PnL_operations_2026-08-01_2026-08-31_stmt_2026-09-23.xlsx"'
        )
        sheet = load_workbook(BytesIO(res.content))["Операции"]
        self.assertEqual(sheet["A2"].value, "Отчёт о прибылях и убытках · Выручка")
        self.assertEqual(sheet["B5"].value, 1800)
        self.assertEqual(sheet.max_row, 10)  # table header on row 8 + August's bank and cash receipts

    def test_lines_export_logs_its_duration(self, _today):
        params = {"template": "professional", "report": "pnl", "line": "rev", "from": "2026-08-01", "to": "2026-08-31"}
        with patch(FETCH, return_value=sample_payload()), self.assertLogs("apps.modules.reports.services", level="INFO") as logs:
            self.client.get(LINES_EXPORT, params, **self._auth(self.director))
        self.assertTrue(any("kind=lines" in line and "ms=" in line for line in logs.output), logs.output)

    # legacy endpoints keep working
    def test_legacy_pnl_keeps_shape_and_adds_section(self, _today):
        with patch("apps.modules.reports.views.fetch_n8n_report_payload", return_value=sample_payload()):
            res = self.client.get("/api/reports/pnl/", **self._auth(self.director))
        self.assertEqual(res.status_code, 200, res.content)
        for key in ("metadata", "totals", "monthly", "rows", "revenue", "operational_expenses", "other_expenses"):
            self.assertIn(key, res.data)
        self.assertTrue(all("section" in row for row in res.data["rows"]))

    def test_legacy_pnl_runtime_error_is_503(self, _today):
        with patch("apps.modules.reports.views.fetch_n8n_report_payload", side_effect=RuntimeError("n8n token missing")):
            res = self.client.get("/api/reports/pnl/", **self._auth(self.director))
        self.assertEqual(res.status_code, 503)

    def test_lines_name_the_request_author(self, _today):
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(
                LINES,
                {"template": "professional", "report": "pnl", "from": "2026-08-01", "to": "2026-08-31", "source": "request"},
                **self._auth(self.director),
            )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual({item["author"] for item in res.data["items"]}, {"Тимур Алиев"})

    def test_lines_filter_by_vendor_ignoring_case_and_spaces(self, _today):
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(
                LINES,
                {"template": "professional", "report": "pnl", "from": "2026-01-01", "to": "2026-09-23",
                 "vendor": "  ооо поставщик "},
                **self._auth(self.director),
            )
        self.assertEqual(res.status_code, 200, res.content)
        # Every sample request is from «ООО Поставщик»: rent 200, marketing 3 × 100, taxes 50.
        self.assertEqual((res.data["count"], res.data["total"]), (5, "550.00"))
        self.assertTrue(all(item["source"] == "request" for item in res.data["items"]))

    def test_lines_vendor_filter_finds_nothing_for_an_unknown_vendor(self, _today):
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(
                LINES,
                {"template": "professional", "report": "pnl", "from": "2026-01-01", "to": "2026-09-23", "vendor": "ИП Никто"},
                **self._auth(self.director),
            )
        self.assertEqual((res.data["count"], res.data["total"]), (0, "0.00"))

    def test_lines_export_filters_by_vendor(self, _today):
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(
                LINES_EXPORT,
                {"template": "professional", "report": "pnl", "from": "2026-01-01", "to": "2026-09-23", "vendor": "ИП Никто"},
                **self._auth(self.director),
            )
        self.assertEqual(res.status_code, 200)
        sheet = load_workbook(BytesIO(res.content))["Операции"]
        # The table header is on row 8; an empty selection writes a note under it instead of rows.
        self.assertEqual(sheet["A9"].value, "Операций за период нет")

    def _vendors_payload(self):
        payload = sample_payload()
        # A second vendor, typed two ways, and a request without a vendor.
        extra = [
            {"id": "40", "date": "2026-08-12", "amount": "700.00", "category": "Аренда", "purpose": "Аренда",
             "description": "Склад", "source": "request", "request_id": "40", "vendor": "ООО Офис"},
            {"id": "41", "date": "2026-08-14", "amount": "90.00", "category": "Аренда", "purpose": "Аренда",
             "description": "Склад, доплата", "source": "request", "request_id": "41", "vendor": "  ооо офис "},
            {"id": "42", "date": "2026-08-15", "amount": "10.00", "category": "Аренда", "purpose": "Аренда",
             "description": "Без поставщика", "source": "request", "request_id": "42", "vendor": ""},
        ]
        payload["operational_expenses"] = payload["operational_expenses"] + extra
        return payload

    def _vendors(self, user, **params):
        query = {"template": "professional", "report": "pnl", "from": "2026-08-01", "to": "2026-08-31", **params}
        with patch(FETCH, return_value=self._vendors_payload()):
            return self.client.get(VENDORS, query, **self._auth(user))

    def test_vendors_rank_request_vendors_by_amount(self, _today):
        res = self._vendors(self.director)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(
            [(v["vendor"], v["amount"], v["requests"]) for v in res.data["items"]],
            [("ООО Офис", "790.00", 2), ("ООО Поставщик", "350.00", 3)],
        )
        self.assertEqual((res.data["count"], res.data["total"]), (2, "1140.00"))
        self.assertEqual(res.data["items"][1]["line_label"], "Аренда")

    def test_vendors_respect_limit_and_line(self, _today):
        limited = self._vendors(self.director, limit=1)
        self.assertEqual([v["vendor"] for v in limited.data["items"]], ["ООО Офис"])
        self.assertEqual(limited.data["count"], 2)
        taxes = self._vendors(self.director, line="other")
        self.assertEqual([(v["vendor"], v["amount"]) for v in taxes.data["items"]], [("ООО Поставщик", "50.00")])

    def test_vendors_reject_bad_queries(self, _today):
        self.assertEqual(self._vendors(self.director, line="opex.ffffffff").status_code, 404)
        self.assertEqual(self._vendors(self.director, limit=0).status_code, 400)
        # An unknown template is a bad request, as on the other statement endpoints.
        self.assertEqual(self._vendors(self.director, template="ghost").status_code, 400)

    def test_vendor_export_names_the_vendor_in_its_title(self, _today):
        with patch(FETCH, return_value=sample_payload()):
            res = self.client.get(
                LINES_EXPORT,
                {"template": "professional", "report": "pnl", "from": "2026-01-01", "to": "2026-09-23",
                 "vendor": "  ооо   поставщик "},
                **self._auth(self.director),
            )
        self.assertEqual(res.status_code, 200)
        sheet = load_workbook(BytesIO(res.content))["Операции"]
        # The vendor's own spelling from the requests, not the one typed into the link.
        self.assertEqual(sheet["A2"].value, "Отчёт о прибылях и убытках · Все разделы · Поставщик: ООО Поставщик")
