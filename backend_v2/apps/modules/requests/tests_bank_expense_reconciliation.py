"""
Tests for requests.bank_expense_reconciliation — the vendor + amount +
payed_at fallback matcher that replaces the reverted PR #240 approach.

Covers: window boundaries, payed_at (not billing_date) as the anchor, the
"never touch an existing link" invariant in both directions, and the
closest-date pairing strategy for multiple payments to the same vendor.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.bank_expense_reconciliation import (
    payed_at_to_date,
    reconcile_bank_expenses_by_vendor_amount_date,
)
from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import BankAccount, Wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _payed_at(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


class BankExpenseReconciliationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-recon", is_active=True)
        self.admin = User.objects.create_user(username="admin-recon", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.bank_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )

    def _make_vendor(self, name="Vendor"):
        return Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name=name, created_by=self.admin,
        )

    def _make_expense(self, *, vendor, doc_date, amount, row_no=1):
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
            vendor=vendor,
            wallet=self.bank_wallet,
        )

    def _make_request(self, *, vendor, amount, payed_date, expense_id="", expense_ref_id=None, title="R"):
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
            vendor_ref=vendor,
            expense_id=expense_id,
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK if expense_ref_id else None,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    # -- payed_at_to_date -----------------------------------------------

    def test_payed_at_to_date_parses_yyyymmdd_int(self):
        self.assertEqual(payed_at_to_date(20260814), date(2026, 8, 14))

    def test_payed_at_to_date_none_when_missing(self):
        self.assertIsNone(payed_at_to_date(None))
        self.assertIsNone(payed_at_to_date(0))

    # -- basic matching ----------------------------------------------------

    def test_matches_within_window(self):
        vendor = self._make_vendor()
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(vendor=vendor, amount="500.00", payed_date=date(2026, 3, 12))

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 1)
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)

    def test_no_match_outside_window(self):
        vendor = self._make_vendor()
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 1), amount="500.00")
        req = self._make_request(vendor=vendor, amount="500.00", payed_date=date(2026, 3, 10))

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_no_match_when_amount_differs(self):
        vendor = self._make_vendor()
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(vendor=vendor, amount="501.00", payed_date=date(2026, 3, 10))

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_no_match_when_payed_at_missing(self):
        vendor = self._make_vendor()
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(vendor=vendor, amount="500.00", payed_date=date(2026, 3, 10))
        req.payed_at = None
        req.save(update_fields=["payed_at"])

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)

    def test_manual_expense_id_is_not_touched(self):
        """A request with a manually-entered (even if not-yet-resolved) expense_id is left alone."""
        vendor = self._make_vendor()
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(
            vendor=vendor, amount="500.00", payed_date=date(2026, 3, 10), expense_id="SOME-DOC-NO",
        )

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    # -- never touch existing links -----------------------------------------

    def test_does_not_relink_already_linked_request(self):
        vendor = self._make_vendor()
        other_expense = self._make_expense(vendor=vendor, doc_date=date(2026, 1, 1), amount="999.00", row_no=1)
        matching_expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500.00", row_no=2)
        req = self._make_request(
            vendor=vendor, amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=other_expense.id,
        )

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, other_expense.id)
        # the genuinely matching expense must stay unclaimed by anyone else too
        self.assertFalse(
            Request.objects.filter(expense_ref_id=matching_expense.id).exists()
        )

    def test_does_not_reclaim_already_claimed_expense(self):
        vendor = self._make_vendor()
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500.00")
        self._make_request(
            vendor=vendor, amount="500.00", payed_date=date(2026, 3, 10),
            expense_ref_id=expense.id, title="Already linked",
        )
        unlinked_req = self._make_request(
            vendor=vendor, amount="500.00", payed_date=date(2026, 3, 11), title="Should stay unlinked",
        )

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        unlinked_req.refresh_from_db()
        self.assertIsNone(unlinked_req.expense_ref_id)

    # -- multiple payments to the same vendor --------------------------------

    def test_multiple_payments_to_same_vendor_paired_by_closest_date(self):
        vendor = self._make_vendor()
        expense_early = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 5), amount="400.00", row_no=1)
        expense_late = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 20), amount="400.00", row_no=2)
        req_early = self._make_request(
            vendor=vendor, amount="400.00", payed_date=date(2026, 3, 6), title="Early",
        )
        req_late = self._make_request(
            vendor=vendor, amount="400.00", payed_date=date(2026, 3, 19), title="Late",
        )

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 2)
        req_early.refresh_from_db()
        req_late.refresh_from_db()
        self.assertEqual(req_early.expense_ref_id, expense_early.id)
        self.assertEqual(req_late.expense_ref_id, expense_late.id)

    def test_ambiguous_pair_outside_each_others_window_stays_unmatched_for_the_far_one(self):
        """
        Vendor has one expense; two same-amount requests are candidates but only
        one is within the window -- only that one should be linked.
        """
        vendor = self._make_vendor()
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="400.00")
        close_req = self._make_request(
            vendor=vendor, amount="400.00", payed_date=date(2026, 3, 11), title="Close",
        )
        far_req = self._make_request(
            vendor=vendor, amount="400.00", payed_date=date(2026, 3, 25), title="Far",
        )

        linked = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 1)
        close_req.refresh_from_db()
        far_req.refresh_from_db()
        self.assertEqual(close_req.expense_ref_id, expense.id)
        self.assertIsNone(far_req.expense_ref_id)

    # -- idempotency ----------------------------------------------------------

    def test_running_twice_is_a_no_op_the_second_time(self):
        vendor = self._make_vendor()
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500.00")
        self._make_request(vendor=vendor, amount="500.00", payed_date=date(2026, 3, 10))

        first = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)
        second = reconcile_bank_expenses_by_vendor_amount_date(tenant=self.tenant)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)


class ReconcileBankExpensesByVendorCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-recon-cmd", is_active=True)
        self.admin = User.objects.create_user(username="admin-recon-cmd", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.bank_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Vendor", created_by=self.admin,
        )

    def test_command_links_for_given_tenant(self):
        expense = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 3, 10),
            process_date=date(2026, 3, 10),
            expense_year=2026,
            expense_month=3,
            expense_day=10,
            doc_no="",
            debit_turnover=Decimal("500.00"),
            payment_purpose="x",
            vendor=self.vendor,
            wallet=self.bank_wallet,
        )
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="R",
            description="",
            amount=Decimal("500.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            vendor_ref=self.vendor,
            expense_id="",
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(date(2026, 3, 11)),
        )

        call_command("reconcile_bank_expenses_by_vendor", tenant=self.tenant.id)

        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
