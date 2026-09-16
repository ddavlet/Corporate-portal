"""
Tests for expense_reconciliation_core.find_and_reconcile — the generic
engine behind expense_reconciliation_adapters. Exercises BANK (has vendor)
and CARD (no vendor) to cover both branches; CASH is structurally
identical to BANK so isn't re-tested here in full.
"""

from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.expense_reconciliation_adapters import BANK, CARD
from apps.modules.requests.expense_reconciliation_core import find_and_reconcile, payed_at_to_date
from apps.modules.requests.models import Request, RequestComment
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import BankAccount, Wallet
from apps.modules.wallets.resolution import get_or_create_corporate_wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _payed_at(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _at_noon(d: date):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


class PayedAtToDateTests(TestCase):
    def test_parses_yyyymmdd_int(self):
        self.assertEqual(payed_at_to_date(20260814), date(2026, 8, 14))

    def test_none_when_missing(self):
        self.assertIsNone(payed_at_to_date(None))
        self.assertIsNone(payed_at_to_date(0))


class FindAndReconcileBankTests(TestCase):
    """Covers the vendor-bearing branch (BANK), including dangling/mismatch."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-core-bank", is_active=True)
        self.admin = User.objects.create_user(username="admin-core-bank", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Vendor", created_by=self.admin,
        )
        system_user = User.objects.create_user(username="system-core-bank", password="x")
        system_user.pk = 1
        system_user.save()

    def _make_expense(self, *, doc_date, amount, vendor=None, row_no=1):
        return BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=row_no,
            doc_date=doc_date,
            process_date=doc_date,
            expense_year=doc_date.year,
            expense_month=doc_date.month,
            expense_day=doc_date.day,
            doc_no="",
            debit_turnover=Decimal(amount),
            payment_purpose="x",
            vendor=vendor or self.vendor,
            wallet=self.wallet,
        )

    _UNSET = object()

    def _make_request(self, *, amount, payed_date, vendor_ref=_UNSET, expense_ref_id=None, title="R"):
        # `vendor_ref=None` must mean "explicitly no vendor" (for the
        # no-vendor-ref test below) — a plain `None` default couldn't
        # distinguish that from "caller didn't pass it, use self.vendor",
        # hence the sentinel.
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title=title,
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=payed_date.replace(day=1),
            vendor_ref=self.vendor if vendor_ref is self._UNSET else vendor_ref,
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK if expense_ref_id else None,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    def test_missing_link_is_repaired(self):
        expense = self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 12))

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["repaired"])
        self.assertEqual(outcomes[0].problem, "missing")
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)

    def test_dangling_link_is_repaired(self):
        good_expense = self._make_expense(doc_date=date(2026, 3, 10), amount="500.00", row_no=1)
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=999999)

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["repaired"])
        self.assertEqual(outcomes[0].problem, "dangling")
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, good_expense.id)

    def test_mismatched_amount_link_is_repaired(self):
        wrong_expense = self._make_expense(doc_date=date(2026, 3, 10), amount="999.00", row_no=1)
        right_expense = self._make_expense(doc_date=date(2026, 3, 10), amount="500.00", row_no=2)
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=wrong_expense.id)

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["repaired"])
        self.assertEqual(outcomes[0].problem, "mismatch")
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, right_expense.id)

    def test_correctly_linked_request_is_left_alone_and_not_reported(self):
        expense = self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        self._make_request(amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=expense.id)

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes, [])

    def test_dry_run_does_not_write(self):
        expense = self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 12))

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=False)

        self.assertEqual(outcomes[0].outcome, "repaired")
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)
        self.assertFalse(RequestComment.objects.filter(request_id=req.pk).exists())

    def test_apply_leaves_system_comment(self):
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 12))

        find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        comment = RequestComment.objects.get(request_id=req.pk)
        self.assertEqual(comment.created_by_id, 1)

    def test_does_not_reclaim_already_correctly_claimed_expense(self):
        expense = self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        self._make_request(amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=expense.id, title="Linked")
        broken = self._make_request(amount="500.00", payed_date=date(2026, 3, 11), title="Should stay unmatched")

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["no_candidate"])
        broken.refresh_from_db()
        self.assertIsNone(broken.expense_ref_id)

    def test_outside_window_is_no_candidate(self):
        self._make_expense(doc_date=date(2026, 3, 1), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10))

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes[0].outcome, "no_candidate")
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_ambiguous_when_two_unclaimed_candidates_in_window(self):
        self._make_expense(doc_date=date(2026, 3, 9), amount="500.00", row_no=1)
        self._make_expense(doc_date=date(2026, 3, 11), amount="500.00", row_no=2)
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10))

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes[0].outcome, "ambiguous")
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_no_vendor_ref_without_fallback_is_no_candidate(self):
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10), vendor_ref=None)

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True, use_name_fallback=False)

        self.assertEqual(outcomes[0].outcome, "no_candidate")
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_problems_filter_restricts_what_gets_examined(self):
        wrong_expense = self._make_expense(doc_date=date(2026, 3, 10), amount="999.00", row_no=1)
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00", row_no=2)
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=wrong_expense.id)

        outcomes = find_and_reconcile(
            adapter=BANK, tenant=self.tenant, apply_changes=True, problems=frozenset({"missing"}),
        )

        self.assertEqual(outcomes, [])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, wrong_expense.id)

    def test_date_range_filter(self):
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00", row_no=1)
        self._make_expense(doc_date=date(2026, 6, 10), amount="500.00", row_no=2)
        in_range = self._make_request(amount="500.00", payed_date=date(2026, 3, 10), title="InRange")
        out_of_range = self._make_request(amount="500.00", payed_date=date(2026, 6, 10), title="OutOfRange")

        outcomes = find_and_reconcile(
            adapter=BANK, tenant=self.tenant, apply_changes=True,
            date_from=20260301, date_to=20260401,
        )

        self.assertEqual([o.request_id for o in outcomes], [in_range.id])
        out_of_range.refresh_from_db()
        self.assertIsNone(out_of_range.expense_ref_id)

    def test_running_twice_is_a_no_op_the_second_time(self):
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        self._make_request(amount="500.00", payed_date=date(2026, 3, 10))

        first = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)
        second = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in first], ["repaired"])
        self.assertEqual(second, [])


class FindAndReconcileCardTests(TestCase):
    """Covers the no-vendor branch (CARD): grouping by amount only."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-core-card", is_active=True)
        self.admin = User.objects.create_user(username="admin-core-card", password="x")
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        system_user = User.objects.create_user(username="system-core-card", password="x")
        system_user.pk = 1
        system_user.save()

    def _make_expense(self, *, expense_date, amount):
        return CardExpense.objects.create(
            tenant=self.tenant,
            title="CARD",
            amount=Decimal(amount),
            currency="UZS",
            expense_at=_at_noon(expense_date),
            wallet=self.wallet,
            created_by=self.admin,
        )

    def _make_request(self, *, amount, payed_date, expense_ref_id=None, title="R"):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title=title,
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD,
            urgency=Request.URGENCY_NORMAL,
            billing_date=payed_date.replace(day=1),
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD if expense_ref_id else None,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    def test_matches_by_amount_and_date_without_vendor(self):
        expense = self._make_expense(expense_date=date(2026, 3, 10), amount="120.00")
        req = self._make_request(amount="120.00", payed_date=date(2026, 3, 11))

        outcomes = find_and_reconcile(adapter=CARD, tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes[0].outcome, "repaired")
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD)

    def test_dangling_card_ref_is_repaired(self):
        expense = self._make_expense(expense_date=date(2026, 3, 10), amount="120.00")
        req = self._make_request(amount="120.00", payed_date=date(2026, 3, 10), expense_ref_id=555555)

        outcomes = find_and_reconcile(adapter=CARD, tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes[0].outcome, "repaired")
        self.assertEqual(outcomes[0].problem, "dangling")
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)


class FindAndReconcileNameFallbackTests(TestCase):
    """Covers use_name_fallback=True: requests with no vendor_ref but a
    free-text `vendor` matching the directory by normalized name."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-core-fallback", is_active=True)
        self.admin = User.objects.create_user(username="admin-core-fallback", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name='ООО "Gevorkyan Trade"', created_by=self.admin,
        )
        system_user = User.objects.create_user(username="system-core-fallback", password="x")
        system_user.pk = 1
        system_user.save()

    def _make_expense(self, *, doc_date, amount):
        return BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=doc_date,
            process_date=doc_date,
            expense_year=doc_date.year,
            expense_month=doc_date.month,
            expense_day=doc_date.day,
            doc_no="",
            debit_turnover=Decimal(amount),
            payment_purpose="x",
            vendor=self.vendor,
            wallet=self.wallet,
        )

    def _make_request_without_vendor_ref(self, *, amount, payed_date, vendor_text):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="R",
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=payed_date.replace(day=1),
            vendor=vendor_text,
            vendor_ref=None,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    def test_name_fallback_links_and_backfills_vendor_ref(self):
        expense = self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request_without_vendor_ref(
            amount="500.00", payed_date=date(2026, 3, 10), vendor_text="Gevorkyan Trade",
        )

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes[0].outcome, "repaired")
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.vendor_ref_id, self.vendor.id)

    def test_name_fallback_disabled_reports_no_candidate(self):
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request_without_vendor_ref(
            amount="500.00", payed_date=date(2026, 3, 10), vendor_text="Gevorkyan Trade",
        )

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True, use_name_fallback=False)

        self.assertEqual(outcomes[0].outcome, "no_candidate")
        req.refresh_from_db()
        self.assertIsNone(req.vendor_ref_id)

    def test_name_fallback_no_match_reports_no_candidate(self):
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request_without_vendor_ref(
            amount="500.00", payed_date=date(2026, 3, 10), vendor_text="Completely Different Co",
        )

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes[0].outcome, "no_candidate")
        req.refresh_from_db()
        self.assertIsNone(req.vendor_ref_id)

    def test_dry_run_name_fallback_does_not_persist_vendor_ref(self):
        self._make_expense(doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request_without_vendor_ref(
            amount="500.00", payed_date=date(2026, 3, 10), vendor_text="Gevorkyan Trade",
        )

        outcomes = find_and_reconcile(adapter=BANK, tenant=self.tenant, apply_changes=False)

        self.assertEqual(outcomes[0].outcome, "repaired")
        req.refresh_from_db()
        self.assertIsNone(req.vendor_ref_id)
        self.assertIsNone(req.expense_ref_id)
