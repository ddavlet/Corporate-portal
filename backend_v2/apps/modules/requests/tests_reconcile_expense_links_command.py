"""
CLI-level tests for reconcile_expense_links — the permanent, filterable
replacement for reconcile_bank_expenses_by_vendor /
link_lemonaqua_transfer_bank_expenses / reconcile_card_expenses_by_amount.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request, RequestComment
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import BankAccount, Wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _payed_at(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


class ReconcileExpenseLinksCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-recon-cmd2", is_active=True)
        self.other_tenant = Tenant.objects.create(name="Other", subdomain="other-recon-cmd2", is_active=True)
        self.admin = User.objects.create_user(username="admin-recon-cmd2", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Vendor", created_by=self.admin,
        )
        system_user = User.objects.create_user(username="system-recon-cmd2", password="x")
        system_user.pk = 1
        system_user.save()

    def _make_expense(self, *, tenant, doc_date, amount, row_no=1, vendor=None):
        return BankExpense.objects.create(
            tenant=tenant,
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

    def _make_request(self, *, tenant, amount, payed_date, expense_ref_id=None, title="R"):
        return Request.objects.create(
            tenant=tenant,
            created_by=self.admin,
            requester=self.admin,
            title=title,
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=payed_date.replace(day=1),
            vendor_ref=self.vendor,
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK if expense_ref_id else None,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    def test_tenant_is_required(self):
        with self.assertRaises(CommandError):
            call_command("reconcile_expense_links")

    def test_unknown_tenant_raises(self):
        with self.assertRaises(CommandError):
            call_command("reconcile_expense_links", tenant=999999)

    def test_dry_run_does_not_write(self):
        expense = self._make_expense(tenant=self.tenant, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(tenant=self.tenant, amount="500.00", payed_date=date(2026, 3, 10))

        call_command("reconcile_expense_links", tenant=self.tenant.id, type=["bank"], stdout=StringIO())

        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_apply_writes_and_leaves_comment(self):
        expense = self._make_expense(tenant=self.tenant, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(tenant=self.tenant, amount="500.00", payed_date=date(2026, 3, 10))

        call_command("reconcile_expense_links", tenant=self.tenant.id, type=["bank"], apply=True, stdout=StringIO())

        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertTrue(RequestComment.objects.filter(request_id=req.pk).exists())

    def test_repairs_dangling_ref_unlike_the_old_commands(self):
        good_expense = self._make_expense(tenant=self.tenant, doc_date=date(2026, 3, 10), amount="500.00", row_no=1)
        req = self._make_request(
            tenant=self.tenant, amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=999999,
        )

        call_command("reconcile_expense_links", tenant=self.tenant.id, type=["bank"], apply=True, stdout=StringIO())

        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, good_expense.id)

    def test_type_filter_restricts_to_requested_types(self):
        self._make_expense(tenant=self.tenant, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(tenant=self.tenant, amount="500.00", payed_date=date(2026, 3, 10))

        call_command("reconcile_expense_links", tenant=self.tenant.id, type=["cash"], apply=True, stdout=StringIO())

        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_no_type_filter_defaults_to_all_three_types(self):
        self._make_expense(tenant=self.tenant, doc_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(tenant=self.tenant, amount="500.00", payed_date=date(2026, 3, 10))

        call_command("reconcile_expense_links", tenant=self.tenant.id, apply=True, stdout=StringIO())

        req.refresh_from_db()
        self.assertIsNotNone(req.expense_ref_id)

    def test_date_range_filter(self):
        self._make_expense(tenant=self.tenant, doc_date=date(2026, 3, 10), amount="500.00", row_no=1)
        self._make_expense(tenant=self.tenant, doc_date=date(2026, 6, 10), amount="500.00", row_no=2)
        in_range = self._make_request(tenant=self.tenant, amount="500.00", payed_date=date(2026, 3, 10), title="InRange")
        out_of_range = self._make_request(tenant=self.tenant, amount="500.00", payed_date=date(2026, 6, 10), title="OutOfRange")

        call_command(
            "reconcile_expense_links", tenant=self.tenant.id, type=["bank"],
            date_from="2026-03-01", date_to="2026-04-01", apply=True, stdout=StringIO(),
        )

        in_range.refresh_from_db()
        out_of_range.refresh_from_db()
        self.assertIsNotNone(in_range.expense_ref_id)
        self.assertIsNone(out_of_range.expense_ref_id)

    def test_invalid_date_format_raises(self):
        with self.assertRaises(CommandError):
            call_command("reconcile_expense_links", tenant=self.tenant.id, date_from="03/10/2026")

    def test_does_not_touch_other_tenants(self):
        self._make_expense(tenant=self.other_tenant, doc_date=date(2026, 3, 10), amount="500.00", vendor=self.vendor)
        req = self._make_request(tenant=self.tenant, amount="500.00", payed_date=date(2026, 3, 10))

        call_command("reconcile_expense_links", tenant=self.tenant.id, type=["bank"], apply=True, stdout=StringIO())

        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)
