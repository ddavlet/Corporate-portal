"""Tests for the fix_lemonhavo_misattributed_bank_expenses one-off command."""

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
    call_command("fix_lemonhavo_misattributed_bank_expenses", stdout=out, **options)
    return out.getvalue()


class FixLemonhavoMisattributedBankExpensesTests(TestCase):
    def setUp(self):
        self.havo = Tenant.objects.create(id=7, name="Lemonfit Havo", subdomain="lemonhavo-fixtest", is_active=True)
        self.fit = Tenant.objects.create(id=1, name="Lemonfit ONE", subdomain="lemonfit-fixtest", is_active=True)
        self.admin = User.objects.create_user(username="admin-havofix", password="x")

        havo_bank_account = BankAccount.objects.create(tenant=self.havo, label="Havo main")
        self.havo_wallet = Wallet.objects.create(
            tenant=self.havo, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=havo_bank_account,
        )

        self.havo_vendor = Vendor.objects.create(
            id=742, tenant=self.havo, kind=Vendor.KIND_TRANSFER,
            name='"MASSIVE DYNAMICS GROUP" MCHJ', created_by=self.admin,
        )
        self.fit_vendor = Vendor.objects.create(
            id=23, tenant=self.fit, kind=Vendor.KIND_TRANSFER,
            name='"MASSIVE DYNAMICS GROUP" MCHJ', created_by=self.admin,
        )

        self.expense_1 = self._make_expense(id=8615, doc_no="121", doc_date=date(2026, 8, 17))
        self.expense_2 = self._make_expense(id=23915, doc_no="151", doc_date=date(2026, 9, 9))

        self.request_1 = self._make_request(id=7738, expense_id="121", billing_date=date(2026, 8, 1))
        self.request_2 = self._make_request(id=8011, expense_id="151", billing_date=date(2026, 9, 1))

    def _make_expense(self, *, id, doc_no, doc_date):
        return BankExpense.objects.create(
            id=id,
            tenant=self.havo,
            created_by=self.admin,
            row_no=1,
            doc_date=doc_date,
            process_date=doc_date,
            expense_year=doc_date.year,
            expense_month=doc_date.month,
            expense_day=doc_date.day,
            doc_no=doc_no,
            debit_turnover=Decimal("3060288.00"),
            payment_purpose="00098 оплата за карты для клиентов",
            vendor=self.havo_vendor,
            wallet=self.havo_wallet,
        )

    def _make_request(self, *, id, expense_id, billing_date):
        return Request.objects.create(
            id=id,
            tenant=self.fit,
            created_by=self.admin,
            requester=self.admin,
            title="Lemonfit ONE",
            description="",
            amount=Decimal("3060288.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=billing_date,
            vendor_ref=self.fit_vendor,
            expense_id=expense_id,
            status=Request.STATUS_PAYED,
            payed_at=int(billing_date.strftime("%Y%m%d")),
        )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.expense_1.refresh_from_db()
        self.request_1.refresh_from_db()
        self.assertEqual(self.expense_1.tenant_id, 7)
        self.assertEqual(self.expense_1.vendor_id, 742)
        self.assertIsNone(self.request_1.expense_ref_id)
        self.assertIn("Would fix: 2", output)
        self.assertIn("Dry run complete", output)

    def test_apply_moves_and_links_both_pairs(self):
        output = _run(apply=True)

        self.expense_1.refresh_from_db()
        self.expense_2.refresh_from_db()
        self.request_1.refresh_from_db()
        self.request_2.refresh_from_db()

        self.assertEqual(self.expense_1.tenant_id, 1)
        self.assertEqual(self.expense_1.vendor_id, 23)
        self.assertEqual(self.request_1.expense_ref_id, 8615)
        self.assertEqual(self.request_1.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)

        self.assertEqual(self.expense_2.tenant_id, 1)
        self.assertEqual(self.expense_2.vendor_id, 23)
        self.assertEqual(self.request_2.expense_ref_id, 23915)
        self.assertEqual(self.request_2.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)

        # The wallet is left untouched — it still records that the money left Havo's account.
        self.assertEqual(self.expense_1.wallet_id, self.havo_wallet.id)

        self.assertIn("Fixed: 2", output)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Fixed: 0", output)
        self.assertIn("Already correct: 2", output)

    def test_unexpected_current_tenant_is_skipped_not_overwritten(self):
        BankExpense.objects.filter(pk=8615).update(tenant_id=self.fit.id, vendor_id=self.fit_vendor.id)

        output = _run(apply=True)

        self.expense_1.refresh_from_db()
        self.assertEqual(self.expense_1.tenant_id, self.fit.id)
        self.assertIn("Skipped (1)", output)
        self.assertIn("unexpected state", output)

    def test_already_linked_request_is_skipped_not_overwritten(self):
        Request.objects.filter(pk=8011).update(expense_ref_id=99999, expense_ref_target=Request.EXPENSE_REF_TARGET_BANK)

        output = _run(apply=True)

        self.request_2.refresh_from_db()
        self.assertEqual(self.request_2.expense_ref_id, 99999)
        self.assertIn("Skipped (1)", output)
        self.assertIn("already linked", output)
