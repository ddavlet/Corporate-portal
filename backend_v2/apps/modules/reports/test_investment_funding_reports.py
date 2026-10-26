from datetime import date, datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.funding import INVESTOR_DEPOSIT_OPERATION
from apps.modules.reports.cashflow_builder import build_cashflow_payload_from_db
from apps.modules.reports.methodology import build_methodology
from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.pnl_builder import build_pnl_payload_from_db
from apps.modules.reports.tests import full_backend_pnl_config
from apps.modules.requests.models import Request
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class InvestmentFundingReportsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="InvRep", subdomain="invrep")
        self.user = User.objects.create_user(username="inv_rep_u", password="x")
        cfg = full_backend_pnl_config(
            request_payment_types_for_pnl=[Request.PAYMENT_TYPE_CASH, Request.PAYMENT_TYPE_TRANSFER]
        )
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source="backend",
            pnl_config=cfg,
            cashflow_source="backend",
            cashflow_config=cfg,
        )

    def _cash_revenue(self, operation, amount="100.00"):
        return CashRevenue.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            wallet=get_or_create_cash_wallet(tenant=self.tenant, currency="UZS"),
            source_year=2026,
            revenue_at=datetime(2026, 3, 5, 10, 0, tzinfo=dt_timezone.utc),
            total_sum=amount,
            operation=operation,
            payload={"operation": operation},
            confirmed=True,
        )

    def _paid_request(self, payment_type):
        return Request.objects.create(
            tenant=self.tenant, created_by=self.user, requester=self.user, title="r", description="",
            amount="40.00", currency="UZS", payment_type=payment_type,
            urgency=Request.URGENCY_NORMAL, billing_date=date(2026, 3, 1),
            payment_purpose="Операционное назначение", status=Request.STATUS_PAYED,
            expense_year=2026, expense_month=3, expense_day=5,
        )

    def test_pnl_excludes_investor_deposit_revenue(self):
        deposit = self._cash_revenue(INVESTOR_DEPOSIT_OPERATION, "500.00")
        regular = self._cash_revenue("Выручка", "100.00")
        revenue_ids = [r["id"] for r in build_pnl_payload_from_db(tenant=self.tenant, query_params={})["revenue"]]
        self.assertNotIn(str(deposit.id), revenue_ids)
        self.assertIn(str(regular.id), revenue_ids)

    def test_pnl_includes_invest_request_expenses(self):
        cash = self._paid_request(Request.PAYMENT_TYPE_INVEST_CASH)
        transfer = self._paid_request(Request.PAYMENT_TYPE_INVEST_TRANSFER)
        pnl = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        ids = [r["id"] for r in pnl["operational_expenses"]]
        self.assertIn(str(cash.id), ids)
        self.assertIn(str(transfer.id), ids)

    def test_cashflow_includes_invest_request_expenses(self):
        cash = self._paid_request(Request.PAYMENT_TYPE_INVEST_CASH)
        cashflow = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})
        self.assertIn(str(cash.id), [r["id"] for r in cashflow["operational_expenses"]])

    def test_cashflow_shows_investor_deposit_category(self):
        deposit = self._cash_revenue(INVESTOR_DEPOSIT_OPERATION, "500.00")
        revenue = build_cashflow_payload_from_db(tenant=self.tenant, query_params={})["revenue"]
        rows = [r for r in revenue if r["id"] == str(deposit.id)]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], INVESTOR_DEPOSIT_OPERATION)

    def test_methodology_mentions_investor_deposit(self):
        rules = {
            r["label"]: r["text"]
            for r in build_methodology(
                report="pnl",
                report_settings=full_backend_pnl_config(),
                source="backend",
                generated_at=datetime(2026, 9, 23, 14, 32),
            )
        }
        self.assertIn("«Вложение инвестора»", rules["Выручка: касса"])
