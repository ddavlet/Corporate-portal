from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.reports.cashflow_builder import build_cashflow_payload_from_db
from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.pnl_builder import build_pnl_payload_from_db
from apps.modules.reports.report_rules import ReportSettingsInvalid
from apps.modules.reports.services import _statement_warnings
from apps.modules.reports.tests import full_backend_pnl_config
from apps.modules.requests.models import Request
from apps.modules.wallets.resolution import get_or_create_bank_wallet
from apps.tenants.models import Tenant

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class CashflowOwnRulesTests(TestCase):
    """Cashflow is built from cashflow_config and PnL from pnl_config: neither report reads the other's rules."""

    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="OwnRules", subdomain="ownrules")
        self.user = User.objects.create_user(username="own_rules_u", password="x")

    def _settings(self, *, pnl_config, cashflow_config):
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source="backend",
            pnl_config=pnl_config,
            cashflow_source="backend",
            cashflow_config=cashflow_config,
        )

    def _paid_request(self, purpose):
        return Request.objects.create(
            tenant=self.tenant, created_by=self.user, requester=self.user, title="r", description="",
            amount="40.00", currency="UZS", payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL, billing_date=date(2026, 3, 1), payment_purpose=purpose,
            status=Request.STATUS_PAYED, expense_year=2026, expense_month=3, expense_day=5,
        )

    def test_cashflow_sections_follow_the_cashflow_rules(self):
        self._settings(
            pnl_config=full_backend_pnl_config(payment_purpose_operational=["Аренда"]),
            cashflow_config=full_backend_pnl_config(payment_purpose_other=["Прочее назначение", "Аренда"]),
        )
        req = self._paid_request("Аренда")
        cashflow = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})
        pnl = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        self.assertEqual([row["id"] for row in cashflow["other_expenses"]], [str(req.id)])
        self.assertEqual([row["id"] for row in pnl["operational_expenses"]], [str(req.id)])

    def test_cashflow_is_built_while_the_pnl_rules_are_broken(self):
        self._settings(pnl_config={}, cashflow_config=full_backend_pnl_config())
        self._paid_request("Операционное назначение")
        self.assertEqual(len(build_cashflow_payload_from_db(tenant=self.tenant, query_params={})["operational_expenses"]), 1)
        with self.assertRaises(ReportSettingsInvalid):
            build_pnl_payload_from_db(tenant=self.tenant, query_params={})

    def test_pnl_is_built_while_the_cashflow_rules_are_broken(self):
        self._settings(pnl_config=full_backend_pnl_config(), cashflow_config={})
        self._paid_request("Операционное назначение")
        self.assertEqual(len(build_pnl_payload_from_db(tenant=self.tenant, query_params={})["operational_expenses"]), 1)
        with self.assertRaises(ReportSettingsInvalid):
            build_cashflow_payload_from_db(tenant=self.tenant, query_params={})

    def test_cashflow_opening_balance_comes_from_its_own_rules(self):
        self._settings(
            pnl_config=full_backend_pnl_config(opening_balance="111"),
            cashflow_config=full_backend_pnl_config(opening_balance="222"),
        )
        payload = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})
        self.assertEqual(payload["report_settings"]["opening_balance"], "222")

    def test_cashflow_never_applies_bank_exclusions(self):
        # Money paid into the charter capital is not income, but it is cash that arrived.
        self._settings(
            pnl_config=full_backend_pnl_config(),
            cashflow_config=full_backend_pnl_config(bank_exclude_purposes=["уставного"]),
        )
        bank = BankRevenue.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            wallet=get_or_create_bank_wallet(tenant=self.tenant),
            doc_date=date(2026, 3, 5),
            process_date=date(2026, 3, 5),
            doc_no="CF-1",
            account_name="ООО Партнёр",
            inn="123456789",
            account_no="20208000123456789012",
            mfo="01001",
            kredit_turnover="100.00",
            payment_purpose="Пополнение уставного капитала",
        )
        revenue = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})["revenue"]
        self.assertIn(str(bank.id), [row["id"] for row in revenue])

    def test_statement_warnings_read_the_reports_own_rules(self):
        self._settings(
            pnl_config=full_backend_pnl_config(payment_purpose_operational=["Операционное назначение", "Аренда"]),
            cashflow_config=full_backend_pnl_config(),
        )
        self._paid_request("Аренда")
        self.assertEqual(_statement_warnings(tenant=self.tenant, report="pnl", source="backend"), [])
        (warning,) = _statement_warnings(tenant=self.tenant, report="cashflow", source="backend")
        self.assertEqual((warning["code"], warning["purposes"]), ("unassigned_purposes", ["Аренда"]))
