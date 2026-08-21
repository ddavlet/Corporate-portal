"""Tests for the fix_bank_expense_vendor_misattribution one-off command."""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import BankAccount, Wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _run(**options):
    out = StringIO()
    call_command("fix_bank_expense_vendor_misattribution", stdout=out, **options)
    return out.getvalue()


class FixBankExpenseVendorMisattributionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=3, name="Lemonfit Aqua", subdomain="lemonaqua-fixtest", is_active=True)
        self.admin = User.objects.create_user(username="admin-fix", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )

        self.wrong_vendor = Vendor.objects.create(
            id=146, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="ANOR BANK", created_by=self.admin,
        )
        self.correct_vendor = Vendor.objects.create(
            id=546, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Ravshan Davletyarov", created_by=self.admin,
        )
        self.other_wrong_vendor = Vendor.objects.create(
            id=761, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Sardor Davletyarov", created_by=self.admin,
        )

        self.expense_big = self._make_expense(id=9830, vendor=self.wrong_vendor, amount="84000000.00")
        self.expense_small = self._make_expense(id=10198, vendor=self.wrong_vendor, amount="36000000.00")
        self.request = Request.objects.create(
            id=7781,
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Lemonfit Aqua",
            description="",
            amount=Decimal("36000000.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 8, 1),
            vendor_ref=self.other_wrong_vendor,
            expense_id="",
            status=Request.STATUS_PAYED,
            payed_at=20260819,
        )

    def _make_expense(self, *, id, vendor, amount):
        d = date(2026, 8, 19)
        return BankExpense.objects.create(
            id=id,
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=d,
            process_date=d,
            expense_year=d.year,
            expense_month=d.month,
            expense_day=d.day,
            doc_no="",
            debit_turnover=Decimal(amount),
            payment_purpose="Ravshan Davletyarov",
            vendor=vendor,
            wallet=self.wallet,
        )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.expense_big.refresh_from_db()
        self.expense_small.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.expense_big.vendor_id, 146)
        self.assertEqual(self.expense_small.vendor_id, 146)
        self.assertEqual(self.request.vendor_ref_id, 761)
        self.assertIn("Would fix: 3", output)
        self.assertIn("Dry run complete", output)

    def test_apply_fixes_all_three_records(self):
        output = _run(apply=True)

        self.expense_big.refresh_from_db()
        self.expense_small.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.expense_big.vendor_id, 546)
        self.assertEqual(self.expense_small.vendor_id, 546)
        self.assertEqual(self.request.vendor_ref_id, 546)
        self.assertIn("Fixed: 3", output)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Fixed: 0", output)
        self.assertIn("Already correct: 3", output)

    def test_unexpected_current_vendor_is_skipped_not_overwritten(self):
        unexpected_vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Someone else", created_by=self.admin,
        )
        BankExpense.objects.filter(pk=9830).update(vendor=unexpected_vendor)

        output = _run(apply=True)

        self.expense_big.refresh_from_db()
        self.assertEqual(self.expense_big.vendor_id, unexpected_vendor.id)
        self.assertIn("Skipped (1)", output)
        self.assertIn("unexpected state", output)
