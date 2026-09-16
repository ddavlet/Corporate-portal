"""
Tests for requests.dangling_bank_expense_ref_repair — repairs Request rows
whose expense_ref_target="bank" but expense_ref_id no longer resolves to a
real BankExpense row (e.g. after a statement re-import regenerated ids).
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.dangling_bank_expense_ref_repair import (
    find_and_repair_dangling_bank_expense_refs,
)
from apps.modules.requests.models import Request, RequestComment
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import BankAccount, Wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _payed_at(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


class FindAndRepairDanglingBankExpenseRefsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Lemonfit Aqua", subdomain="lemonaqua-dangling-test", is_active=True)
        self.admin = User.objects.create_user(username="admin-dangling", password="x")
        if not User.objects.filter(pk=1).exists():
            User.objects.create_user(username="app", password="x", full_name="Система")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.bank_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="GEVORKYAN TIGRAN GEVORGOVICH", created_by=self.admin,
        )

    def _make_expense(self, *, doc_date, amount, row_no=1, vendor=None):
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
            wallet=self.bank_wallet,
        )

    _VENDOR_REF_DEFAULT = object()

    def _make_request(self, *, amount, payed_date, expense_ref_id, vendor_ref=_VENDOR_REF_DEFAULT, title="R"):
        resolved_vendor_ref = self.vendor if vendor_ref is self._VENDOR_REF_DEFAULT else vendor_ref
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
            vendor_ref=resolved_vendor_ref,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
        )

    def test_repairs_dangling_ref_to_matching_unclaimed_expense(self):
        expense = self._make_expense(doc_date=date(2026, 9, 2), amount="25830500.00")
        req = self._make_request(amount="25830500.00", payed_date=date(2026, 9, 2), expense_ref_id=999999)

        results = find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["repaired"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)

    def test_dry_run_does_not_write(self):
        expense = self._make_expense(doc_date=date(2026, 9, 2), amount="100000.00")
        req = self._make_request(amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=999999)

        results = find_and_repair_dangling_bank_expense_refs(apply_changes=False)

        self.assertEqual([r.outcome for r in results], ["repaired"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, 999999)
        self.assertNotEqual(req.expense_ref_id, expense.id)

    def test_does_not_touch_requests_whose_ref_still_resolves(self):
        expense = self._make_expense(doc_date=date(2026, 9, 2), amount="100000.00")
        req = self._make_request(amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=expense.id)

        results = find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        self.assertEqual(results, [])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)

    def test_ambiguous_when_multiple_unclaimed_candidates(self):
        self._make_expense(doc_date=date(2026, 9, 1), amount="100000.00", row_no=1)
        self._make_expense(doc_date=date(2026, 9, 3), amount="100000.00", row_no=2)
        req = self._make_request(amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=999999)

        results = find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["ambiguous"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, 999999)

    def test_no_candidate_reported_when_nothing_matches(self):
        req = self._make_request(amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=999999)

        results = find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["no_candidate"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, 999999)

    def test_does_not_reclaim_expense_already_used_by_another_request(self):
        expense = self._make_expense(doc_date=date(2026, 9, 2), amount="100000.00")
        already_linked = self._make_request(
            amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=expense.id, title="Already linked",
        )
        self.assertEqual(already_linked.expense_ref_id, expense.id)
        dangling = self._make_request(
            amount="100000.00", payed_date=date(2026, 9, 3), expense_ref_id=888888, title="Dangling",
        )

        results = find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        outcomes = {r.request_id: r.outcome for r in results}
        self.assertEqual(outcomes[dangling.pk], "no_candidate")
        dangling.refresh_from_db()
        self.assertEqual(dangling.expense_ref_id, 888888)

    def test_requests_without_vendor_ref_are_skipped(self):
        self._make_expense(doc_date=date(2026, 9, 2), amount="100000.00")
        req = self._make_request(
            amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=999999, vendor_ref=None,
        )

        results = find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        self.assertEqual(results, [])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, 999999)

    def test_leaves_system_comment_when_applied(self):
        expense = self._make_expense(doc_date=date(2026, 9, 2), amount="100000.00")
        req = self._make_request(amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=999999)

        find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        comments = list(RequestComment.objects.filter(request=req))
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].created_by_id, 1)
        self.assertIn(str(expense.id), comments[0].body)
        self.assertIn("999999", comments[0].body)

    def test_idempotent_second_run_is_no_op(self):
        self._make_expense(doc_date=date(2026, 9, 2), amount="100000.00")
        self._make_request(amount="100000.00", payed_date=date(2026, 9, 2), expense_ref_id=999999)

        first = find_and_repair_dangling_bank_expense_refs(apply_changes=True)
        second = find_and_repair_dangling_bank_expense_refs(apply_changes=True)

        self.assertEqual([r.outcome for r in first], ["repaired"])
        self.assertEqual(second, [])


class RepairDanglingBankExpenseRefsCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Lemonfit Aqua", subdomain="lemonaqua-dangling-cmd", is_active=True)
        self.admin = User.objects.create_user(username="admin-dangling-cmd", password="x")
        if not User.objects.filter(pk=1).exists():
            User.objects.create_user(username="app", password="x", full_name="Система")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.bank_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="MAXSUSTRANS", created_by=self.admin,
        )

    def test_command_apply_writes_repair(self):
        expense = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 9, 2),
            process_date=date(2026, 9, 2),
            expense_year=2026,
            expense_month=9,
            expense_day=2,
            doc_no="",
            debit_turnover=Decimal("604650.00"),
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
            amount=Decimal("604650.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1),
            vendor_ref=self.vendor,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(date(2026, 9, 2)),
            expense_ref_id=999999,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
        )

        call_command("repair_dangling_bank_expense_refs", "--apply")

        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)

    def test_command_without_apply_is_dry_run(self):
        BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 9, 2),
            process_date=date(2026, 9, 2),
            expense_year=2026,
            expense_month=9,
            expense_day=2,
            doc_no="",
            debit_turnover=Decimal("604650.00"),
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
            amount=Decimal("604650.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1),
            vendor_ref=self.vendor,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(date(2026, 9, 2)),
            expense_ref_id=999999,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
        )

        call_command("repair_dangling_bank_expense_refs")

        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, 999999)
