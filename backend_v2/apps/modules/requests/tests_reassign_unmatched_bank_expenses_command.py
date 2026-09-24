"""Tests for the reassign_unmatched_bank_expenses management command."""

from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request, RequestComment
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.resolution import get_or_create_bank_wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _run(**options):
    out = StringIO()
    call_command("reassign_unmatched_bank_expenses", stdout=out, **options)
    return out.getvalue()


class ReassignUnmatchedBankExpensesCommandTests(TestCase):
    def setUp(self):
        self.system_user = User.objects.create_user(id=1, username="app", full_name="Система", password="x")
        self.source = Tenant.objects.create(name="Lemonfit ONE", subdomain="reassign-cmd-one", is_active=True)
        self.target = Tenant.objects.create(name="Lemonfit Havo", subdomain="reassign-cmd-havo", is_active=True)
        self.vendor = Vendor.objects.create(
            tenant=self.source, kind=Vendor.KIND_TRANSFER, name="Казначейство",
            account_number="23402000300100000000", created_by=self.system_user,
        )
        self.expense = BankExpense.objects.create(
            tenant=self.source, created_by=self.system_user, row_no=0,
            doc_date=date(2026, 9, 15), process_date=date(2026, 9, 15),
            expense_year=2026, expense_month=9, expense_day=15,
            doc_no="57", debit_turnover="3473685.00", payment_purpose="налог на дивиденды",
            vendor=self.vendor, wallet=get_or_create_bank_wallet(tenant=self.source),
        )
        self.req = Request.objects.create(
            tenant=self.target, created_by=self.system_user, title="Налог на дивиденды",
            amount="3473685.00", currency="UZS", payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL, billing_date=date(2026, 9, 1),
            status=Request.STATUS_PAYED, expense_id="57", expense_year=2026,
        )

    def _args(self, **extra):
        return {"from_subdomain": "reassign-cmd-one", "to_subdomain": "reassign-cmd-havo", **extra}

    def test_dry_run_makes_no_changes(self):
        output = _run(**self._args())

        self.expense.refresh_from_db()
        self.req.refresh_from_db()
        self.assertEqual(self.expense.tenant_id, self.source.id)
        self.assertIsNone(self.req.expense_ref_id)
        self.assertIn(f"BankExpense {self.expense.pk}", output)
        self.assertIn("Would reassign: 1", output)
        self.assertFalse(RequestComment.objects.exists())

    def test_apply_moves_expense_links_request_and_comments(self):
        output = _run(**self._args(apply=True))

        self.expense.refresh_from_db()
        self.req.refresh_from_db()
        self.assertEqual(self.expense.tenant_id, self.target.id)
        self.assertEqual(self.expense.wallet.tenant_id, self.target.id)
        self.assertEqual(self.expense.vendor.tenant_id, self.target.id)
        self.assertEqual(self.req.expense_ref_id, self.expense.pk)
        self.assertEqual(self.req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)
        self.assertIn("Reassigned: 1", output)

        comment = RequestComment.objects.get(request=self.req)
        self.assertEqual(comment.created_by_id, 1)
        self.assertIn(str(self.expense.pk), comment.body)

    def test_apply_is_idempotent(self):
        _run(**self._args(apply=True))
        output = _run(**self._args(apply=True))

        self.assertIn("Reassigned: 0", output)
        self.assertEqual(RequestComment.objects.filter(request=self.req).count(), 1)

    def test_same_tenant_is_rejected(self):
        with self.assertRaises(CommandError):
            _run(from_subdomain="reassign-cmd-one", to_subdomain="reassign-cmd-one")

    def test_unknown_tenant_is_rejected(self):
        with self.assertRaises(CommandError):
            _run(from_subdomain="reassign-cmd-one", to_subdomain="nope")
