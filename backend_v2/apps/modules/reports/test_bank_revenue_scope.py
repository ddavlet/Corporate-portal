from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.reports.bank_revenue_scope import report_bank_revenues
from apps.modules.reports.cashflow_builder import build_cashflow_payload_from_db
from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.pnl_builder import build_pnl_payload_from_db
from apps.modules.reports.tests import full_backend_pnl_config
from apps.modules.wallets.models import BankAccount
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account
from apps.tenants.models import Tenant

User = get_user_model()

MAIN = "20208000000000000001"
RESERVE = "20208000000000000002"
INFO = "20208000000000000003"
SERVICE = "20208000000000000004"
USD = "20208840000000000005"
PARTNER = "20208000000000000099"


@override_settings(BASE_DOMAIN="example.com", REPORTS_CACHE_TTL_SECONDS=60)
class BankRevenueScopeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Scope", subdomain="scope")
        self.user = User.objects.create_user(username="scope_u", password="x")
        A = BankAccount.AccountType
        self.main = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no=MAIN, mfo="01001")
        self.reserve = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no=RESERVE, mfo="01001", account_type=A.CONTROLLED
        )
        self.info = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no=INFO, mfo="01001", account_type=A.INFORMATIONAL
        )
        self.service = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no=SERVICE, mfo="01001", account_type=A.SERVICE
        )
        self.usd = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no=USD, mfo="01001", currency="USD", account_type=A.CONTROLLED
        )

    def _rev(self, wallet, doc_no, account_no=PARTNER, mfo="1001"):
        return BankRevenue.objects.create(
            tenant=self.tenant, created_by=self.user, wallet=wallet,
            doc_date=date(2026, 3, 5), process_date=date(2026, 3, 5), doc_no=doc_no,
            account_name="ООО Партнёр", inn="123456789", account_no=account_no, mfo=mfo,
            kredit_turnover="100.00", payment_purpose="Оплата",
        )

    def _scope_ids(self):
        return {r.id for r in report_bank_revenues(tenant=self.tenant, start=date(2026, 1, 1))}

    def test_includes_controlled_uzs(self):
        # BankRevenue.wallet is non-nullable, so there is no wallet-less case.
        a = self._rev(self.main, "A")
        b = self._rev(self.reserve, "B")
        self.assertEqual(self._scope_ids(), {a.id, b.id})

    def test_excludes_informational_service_and_foreign_currency(self):
        ok = self._rev(self.main, "OK")
        self._rev(self.info, "I")
        self._rev(self.service, "S")
        self._rev(self.usd, "U")
        self.assertEqual(self._scope_ids(), {ok.id})

    def test_excludes_transfer_from_own_account(self):
        ok = self._rev(self.main, "OK")
        self._rev(self.reserve, "T1", account_no=MAIN, mfo="1001")  # MFO without leading zero
        self._rev(self.reserve, "T2", account_no=f" {MAIN} ")
        self.assertEqual(self._scope_ids(), {ok.id})

    def test_pnl_and_cashflow_use_scope(self):
        TenantReportSettings.objects.create(
            tenant=self.tenant, pnl_source="backend", pnl_config=full_backend_pnl_config(opening_balance="0"),
            cashflow_source="backend", cashflow_config=full_backend_pnl_config(opening_balance="0"),
        )
        ok = self._rev(self.main, "OK")
        bad = self._rev(self.info, "I")
        own = self._rev(self.reserve, "T", account_no=MAIN)
        for build in (build_pnl_payload_from_db, build_cashflow_payload_from_db):
            ids = {row["id"] for row in build(tenant=self.tenant, query_params={})["revenue"]}
            self.assertIn(str(ok.id), ids)
            self.assertNotIn(str(bad.id), ids)
            self.assertNotIn(str(own.id), ids)
