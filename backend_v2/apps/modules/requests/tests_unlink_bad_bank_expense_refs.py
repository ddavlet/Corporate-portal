"""Tests for the unlink_bad_bank_expense_refs one-off command."""

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
    call_command("unlink_bad_bank_expense_refs", stdout=out, **options)
    return out.getvalue()


class UnlinkBadBankExpenseRefsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=1, name="Lemonfit ONE", subdomain="lemonfit-fixtest", is_active=True)
        self.admin = User.objects.create_user(username="admin-unlink", password="x")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Vendor", created_by=self.admin,
        )

        # The two BankExpense rows each request wrongly points to, with a
        # different amount than the request they're linked from.
        self.wrong_expense_615 = self._make_expense(id=27172, amount="820000.00")
        self.wrong_expense_670 = self._make_expense(id=27158, amount="980000.00")

        self.request_615 = self._make_request(
            id=615, amount="4000000.00", expense_ref_id=27172,
        )
        self.request_670 = self._make_request(
            id=670, amount="5263158.00", expense_ref_id=27158,
        )

    def _make_expense(self, *, id, amount):
        d = date(2026, 1, 20)
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
            payment_purpose="x",
            vendor=self.vendor,
            wallet=self.wallet,
        )

    def _make_request(self, *, id, amount, expense_ref_id):
        return Request.objects.create(
            id=id,
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Lemonfit ONE",
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            vendor_ref=self.vendor,
            expense_id="",
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            status=Request.STATUS_PAYED,
            payed_at=20260324,
        )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.request_615.refresh_from_db()
        self.request_670.refresh_from_db()
        self.assertEqual(self.request_615.expense_ref_id, 27172)
        self.assertEqual(self.request_670.expense_ref_id, 27158)
        self.assertIn("Would fix: 2", output)
        self.assertIn("Dry run complete", output)

    def test_apply_clears_both_refs(self):
        output = _run(apply=True)

        self.request_615.refresh_from_db()
        self.request_670.refresh_from_db()
        self.assertIsNone(self.request_615.expense_ref_id)
        self.assertIsNone(self.request_615.expense_ref_target)
        self.assertIsNone(self.request_670.expense_ref_id)
        self.assertIsNone(self.request_670.expense_ref_target)
        self.assertIn("Fixed: 2", output)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Fixed: 0", output)
        self.assertIn("Already unlinked: 2", output)

    def test_unexpected_current_ref_is_skipped_not_overwritten(self):
        BankExpense.objects.filter(pk=27172).update(debit_turnover=Decimal("4000000.00"))

        output = _run(apply=True)

        self.request_615.refresh_from_db()
        self.assertEqual(self.request_615.expense_ref_id, 27172)
        self.assertIn("Skipped (1)", output)
        self.assertIn("no longer looks corrupted", output)
