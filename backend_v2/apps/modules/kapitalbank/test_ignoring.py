import datetime as dt
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.kapitalbank import ignoring
from apps.modules.kapitalbank.fixtures import ACCOUNT_1, MFO, KapitalbankFixtures
from apps.modules.kapitalbank.ignoring import ignore_pending
from apps.modules.kapitalbank.models import BankAccountLink
from apps.tenants.models import Tenant

NOW = dt.datetime(2026, 10, 30, 10, 0, tzinfo=dt.timezone.utc)
FEES = "16401000000000000001"
TRANSIT = "23510000000000000001"
MISSING = "99999000000000000001"


class IgnorePendingTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _link(self, account_no, tenant=None, **kw):
        return BankAccountLink.objects.create(
            tenant=tenant or self.tenant, account_no=account_no, branch=MFO, name=f"Счёт {account_no[-4:]}", **kw
        )

    def test_dry_run_writes_nothing(self):
        link = self._link(FEES)

        results = ignore_pending(tenant=self.tenant, account_nos=[FEES], reason="Комиссии", now=NOW)

        self.assertEqual([(r.link, r.matched, r.ignored) for r in results], [(link, True, False)])
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)
        self.assertEqual(link.ignore_reason, "")

    def test_apply_ignores_pending_with_reason(self):
        fees, transit = self._link(FEES), self._link(TRANSIT)

        results = ignore_pending(
            tenant=self.tenant, account_nos=[FEES, TRANSIT, FEES], reason="  Служебный счёт  ", apply=True, now=NOW
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ignored for r in results))
        for link in (fees, transit):
            link.refresh_from_db()
            self.assertEqual(link.decision, BankAccountLink.IGNORED)
            self.assertEqual(link.ignore_reason, "Служебный счёт")
            self.assertEqual(link.decided_at, NOW)
            self.assertIsNone(link.decided_by)

    def test_linked_and_ignored_are_not_changed(self):
        linked = self._link(ACCOUNT_1, decision=BankAccountLink.LINKED, bank_account=self.bank_account1)
        old = self._link(FEES, decision=BankAccountLink.IGNORED, ignore_reason="старая")

        results = ignore_pending(
            tenant=self.tenant, account_nos=[ACCOUNT_1, FEES], reason="Новая", apply=True, now=NOW
        )

        self.assertEqual({r.skip_reason for r in results}, {ignoring.ALREADY_DECIDED})
        self.assertFalse(any(r.ignored for r in results))
        linked.refresh_from_db()
        old.refresh_from_db()
        self.assertEqual(linked.decision, BankAccountLink.LINKED)
        self.assertEqual(linked.bank_account, self.bank_account1)
        self.assertEqual(old.ignore_reason, "старая")

    def test_other_tenant_and_unknown_numbers_are_not_found(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        foreign = self._link(FEES, tenant=other)

        results = ignore_pending(tenant=self.tenant, account_nos=[FEES, MISSING], reason="x", apply=True, now=NOW)

        self.assertEqual([(r.account_no, r.link, r.skip_reason) for r in results], [
            (FEES, None, ignoring.NOT_FOUND),
            (MISSING, None, ignoring.NOT_FOUND),
        ])
        foreign.refresh_from_db()
        self.assertEqual(foreign.decision, BankAccountLink.PENDING)

    def test_empty_reason_is_rejected(self):
        self._link(FEES)
        with self.assertRaises(ValueError):
            ignore_pending(tenant=self.tenant, account_nos=[FEES], reason="  ", apply=True, now=NOW)
        self.assertEqual(BankAccountLink.objects.get(account_no=FEES).decision, BankAccountLink.PENDING)


class IgnoreCommandTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.fees = BankAccountLink.objects.create(tenant=self.tenant, account_no=FEES, branch=MFO, name="Комиссии")
        self.transit = BankAccountLink.objects.create(tenant=self.tenant, account_no=TRANSIT, branch=MFO, name="Транзит")

    def _run(self, *args):
        out = StringIO()
        call_command("ignore_kapitalbank_accounts", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_by_default(self):
        out = self._run(f"--tenant={self.tenant.subdomain}", f"--account={FEES},{TRANSIT}", "--reason=Служебный")

        self.assertIn("(dry-run)", out)
        self.assertIn("would_ignore=2 skipped=0", out)
        self.assertEqual(BankAccountLink.objects.filter(decision=BankAccountLink.PENDING).count(), 2)

    def test_apply_with_repeated_account_option(self):
        out = self._run(
            f"--tenant={self.tenant.subdomain}",
            f"--account={FEES}",
            f"--account={MISSING}",
            "--reason=Служебный счёт банка",
            "--apply",
        )

        self.assertIn("ignored=1 skipped=1", out)
        self.assertIn(f"{MISSING} | | | пропущен", out)
        self.fees.refresh_from_db()
        self.transit.refresh_from_db()
        self.assertEqual(self.fees.decision, BankAccountLink.IGNORED)
        self.assertEqual(self.fees.ignore_reason, "Служебный счёт банка")
        self.assertEqual(self.transit.decision, BankAccountLink.PENDING)

    def test_bad_input_is_rejected(self):
        tenant = f"--tenant={self.tenant.subdomain}"
        for args in (
            ("--tenant=nope", f"--account={FEES}", "--reason=x"),
            (tenant, "--account=1640-1", "--reason=x"),
            (tenant, "--account=,", "--reason=x"),
            (tenant, f"--account={FEES}", "--reason=  "),
        ):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self._run(*args, "--apply")
        self.assertEqual(BankAccountLink.objects.filter(decision=BankAccountLink.PENDING).count(), 2)
