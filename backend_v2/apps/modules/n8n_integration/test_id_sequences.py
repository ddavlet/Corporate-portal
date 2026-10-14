from io import StringIO
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from apps.common.db_sequences import ensure_sequence_ahead, find_sequence_lag
from apps.modules.cashier.models import CashRevenue
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant

User = get_user_model()


@skipUnless(connection.vendor == "postgresql", "id sequences are a PostgreSQL concern")
class IdSequenceRepairTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Seq", subdomain="seqtest", is_active=True)
        self.user = User.objects.create_user(username="seq-user", password="x")
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")

    def _revenue(self, **kwargs) -> CashRevenue:
        return CashRevenue.objects.create(
            tenant=self.tenant, wallet=self.wallet, created_by=self.user, total_sum=1, **kwargs
        )

    def _lag_cash_revenues(self) -> int:
        """Insert a row with an explicit id the way n8n imports do; returns that id."""
        probe = self._revenue()
        taken = probe.pk + 1
        self._revenue(id=taken)
        return taken

    def test_dry_run_reports_lag_and_changes_nothing(self):
        taken = self._lag_cash_revenues()
        out = StringIO()
        call_command("repair_id_sequences", stdout=out)
        self.assertIn("cashier_cashrevenue", out.getvalue())
        self.assertIn("Dry-run", out.getvalue())
        lag = find_sequence_lag(CashRevenue)
        self.assertIsNotNone(lag)
        self.assertEqual(lag.max_id, taken)

    def test_apply_lets_the_next_insert_through(self):
        taken = self._lag_cash_revenues()
        call_command("repair_id_sequences", "--apply", stdout=StringIO())
        self.assertIsNone(find_sequence_lag(CashRevenue))
        self.assertGreater(self._revenue().pk, taken)

    def test_ensure_never_moves_the_sequence_backwards(self):
        self._revenue()
        newest = self._revenue()
        handed_out = newest.pk
        newest.delete()
        ensure_sequence_ahead(CashRevenue)
        self.assertGreater(self._revenue().pk, handed_out)
