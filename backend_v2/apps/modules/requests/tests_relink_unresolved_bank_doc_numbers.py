"""
Tests for relink_unresolved_bank_doc_numbers: PAYED bank заявки with a typed
doc number (`expense_id`) that never resolved to a BankExpense.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request, RequestComment
from apps.modules.requests.unresolved_bank_doc_reconciliation import relink_unresolved_bank_doc_numbers
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import BankAccount, Wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _payed_at(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


class RelinkUnresolvedBankDocNumbersTests(TestCase):
    def setUp(self):
        if not User.objects.filter(pk=1).exists():
            User.objects.create_user(username="system-relink-doc", password="x", full_name="Система")
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-relink-doc", is_active=True)
        self.admin = User.objects.create_user(username="admin-relink-doc", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.payee = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Payee", created_by=self.admin,
        )
        self.bank_vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="ANOR BANK", created_by=self.admin,
        )
        self._row = 0

    def _expense(self, *, doc_no, doc_date, amount, vendor=None):
        self._row += 1
        return BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=self._row,
            doc_date=doc_date,
            process_date=doc_date,
            expense_year=doc_date.year,
            expense_month=doc_date.month,
            expense_day=doc_date.day,
            doc_no=doc_no,
            debit_turnover=Decimal(amount),
            payment_purpose=f"p{self._row}",
            vendor=vendor or self.bank_vendor,
            wallet=self.wallet,
        )

    def _request(self, *, amount, payed_date, expense_id, expense_ref_id=None):
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
            vendor_ref=self.payee,
            expense_id=expense_id,
            expense_year=payed_date.year,
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK if expense_ref_id else None,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    def test_wrong_typed_doc_no_is_linked_by_amount_and_date_and_doc_no_fixed(self):
        expense = self._expense(doc_no="205", doc_date=date(2026, 10, 6), amount="48310000.00")
        req = self._request(amount="48310000.00", payed_date=date(2026, 10, 6), expense_id="25")

        outcomes = relink_unresolved_bank_doc_numbers(tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["linked_by_amount_date"])
        self.assertTrue(outcomes[0].vendor_differs)
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)
        self.assertEqual(req.expense_id, "205")
        self.assertEqual(req.vendor_ref_id, self.payee.id)
        comment = RequestComment.objects.get(request_id=req.pk)
        self.assertEqual(comment.created_by_id, 1)
        self.assertIn("№25", comment.body)

    def test_dry_run_does_not_write(self):
        self._expense(doc_no="61", doc_date=date(2026, 10, 8), amount="2292000.00")
        req = self._request(amount="2292000.00", payed_date=date(2026, 10, 9), expense_id="62")

        outcomes = relink_unresolved_bank_doc_numbers(tenant=self.tenant, apply_changes=False)

        self.assertEqual([o.outcome for o in outcomes], ["linked_by_amount_date"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)
        self.assertEqual(req.expense_id, "62")
        self.assertFalse(RequestComment.objects.filter(request_id=req.pk).exists())

    def test_typed_doc_no_that_now_resolves_is_linked_by_doc_no(self):
        expense = self._expense(doc_no="186", doc_date=date(2026, 9, 25), amount="100.00", vendor=self.payee)
        req = self._request(amount="100.00", payed_date=date(2026, 9, 25), expense_id="186")

        outcomes = relink_unresolved_bank_doc_numbers(tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["linked_by_doc_no"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)

    def test_two_equally_close_expenses_are_ambiguous(self):
        self._expense(doc_no="1", doc_date=date(2026, 9, 25), amount="500.00")
        self._expense(doc_no="2", doc_date=date(2026, 9, 25), amount="500.00")
        req = self._request(amount="500.00", payed_date=date(2026, 9, 25), expense_id="999")

        outcomes = relink_unresolved_bank_doc_numbers(tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["ambiguous"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_expense_claimed_by_another_request_is_not_reused(self):
        expense = self._expense(doc_no="62", doc_date=date(2026, 10, 8), amount="700.00")
        self._request(amount="700.00", payed_date=date(2026, 10, 9), expense_id="62", expense_ref_id=expense.id)
        req = self._request(amount="700.00", payed_date=date(2026, 10, 9), expense_id="61")

        outcomes = relink_unresolved_bank_doc_numbers(tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["no_candidate"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_expense_outside_window_is_not_linked(self):
        self._expense(doc_no="10", doc_date=date(2026, 9, 1), amount="800.00")
        req = self._request(amount="800.00", payed_date=date(2026, 9, 10), expense_id="11")

        outcomes = relink_unresolved_bank_doc_numbers(tenant=self.tenant, apply_changes=True)

        self.assertEqual([o.outcome for o in outcomes], ["no_candidate"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_request_without_typed_doc_no_is_left_to_core_engine(self):
        self._expense(doc_no="5", doc_date=date(2026, 9, 25), amount="900.00")
        self._request(amount="900.00", payed_date=date(2026, 9, 25), expense_id="")

        outcomes = relink_unresolved_bank_doc_numbers(tenant=self.tenant, apply_changes=True)

        self.assertEqual(outcomes, [])

    def test_command_dry_run_then_apply(self):
        expense = self._expense(doc_no="187", doc_date=date(2026, 9, 25), amount="96620000.00")
        req = self._request(amount="96620000.00", payed_date=date(2026, 9, 25), expense_id="181")

        out = StringIO()
        call_command("relink_unresolved_bank_doc_numbers", tenant=[self.tenant.subdomain], stdout=out)
        self.assertIn("Would link: 1", out.getvalue())
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

        call_command("relink_unresolved_bank_doc_numbers", tenant=[str(self.tenant.id)], apply=True, stdout=StringIO())
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.expense_id, "187")
