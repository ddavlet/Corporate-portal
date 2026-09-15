"""
Tests for requests.lemonaqua_transfer_bank_expense_name_matching — the
normalized-vendor-name backfill that resolves `vendor_ref` (and links the
matching bank expense) for lemonaqua Transfer/Topup requests that only carry
free-text `vendor`.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.lemonaqua_transfer_bank_expense_name_matching import (
    LEMONAQUA_TENANT_ID,
    find_and_link_lemonaqua_transfer_bank_expenses,
    normalize_vendor_name,
)
from apps.modules.requests.models import Request, RequestComment
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import BankAccount, Wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _payed_at(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


class NormalizeVendorNameTests(TestCase):
    def test_strips_quotes_and_legal_suffix(self):
        self.assertEqual(normalize_vendor_name('"NIMEX DST" MCHJ QK'), "NIMEX DST")

    def test_strips_ooo_prefix_and_guillemets(self):
        self.assertEqual(normalize_vendor_name("ООО «Systems FX»"), "SYSTEMS FX")

    def test_collapses_whitespace_and_uppercases(self):
        self.assertEqual(normalize_vendor_name("  Sportovar  "), "SPORTOVAR")

    def test_does_not_collapse_a_genuine_spelling_difference(self):
        self.assertNotEqual(normalize_vendor_name("Gevprkyan Tigran"), normalize_vendor_name("GEVORKYAN TIGRAN"))


class FindAndLinkLemonaquaTransferBankExpensesTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=LEMONAQUA_TENANT_ID, name="Lemonfit Aqua", subdomain="lemonaqua-test", is_active=True)
        self.admin = User.objects.create_user(username="admin-lemonaqua", password="x")
        # pk=1 is the convention _system_user() relies on for automated actions.
        if not User.objects.filter(pk=1).exists():
            User.objects.create_user(username="app", password="x", full_name="Система")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.bank_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )

    def _make_vendor(self, name):
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

    def _make_request(self, *, vendor_text, amount, payed_date, payment_type=Request.PAYMENT_TYPE_TRANSFER, title="R"):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title=title,
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=payment_type,
            urgency=Request.URGENCY_NORMAL,
            billing_date=payed_date.replace(day=1),
            vendor=vendor_text,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    def test_links_on_exact_normalized_name_and_amount_within_window(self):
        vendor = self._make_vendor('"NIMEX DST" MCHJ QK')
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="580000.00")
        req = self._make_request(vendor_text="NIMEX DST  ", amount="580000.00", payed_date=date(2026, 3, 12))

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["linked"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)
        self.assertEqual(req.vendor_ref_id, vendor.id)

    def test_dry_run_does_not_write(self):
        vendor = self._make_vendor("SPORTOVAR")
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="100000.00")
        req = self._make_request(vendor_text="Sportovar", amount="100000.00", payed_date=date(2026, 3, 10))

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=False)

        self.assertEqual([r.outcome for r in results], ["linked"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)
        self.assertIsNone(req.vendor_ref_id)

    def test_no_name_match_left_unlinked(self):
        self._make_request(vendor_text="Unknown Vendor Co", amount="100000.00", payed_date=date(2026, 3, 10))

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["no_name_match"])

    def test_typo_does_not_fuzzy_match(self):
        """Conservative by design: a near-miss spelling is reported, never linked."""
        vendor = self._make_vendor("GEVORKYAN TIGRAN GEVORGOVICH")
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="500000.00")
        self._make_request(vendor_text="Gevprkyan Tigran", amount="500000.00", payed_date=date(2026, 3, 10))

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["no_name_match"])

    def test_ambiguous_when_multiple_unclaimed_candidates(self):
        vendor = self._make_vendor("STAR CUP")
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 9), amount="200000.00", row_no=1)
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 11), amount="200000.00", row_no=2)
        req = self._make_request(vendor_text="Star cup", amount="200000.00", payed_date=date(2026, 3, 10))

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["ambiguous"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_two_vendor_accounts_same_name_are_pooled(self):
        """Same legal entity, two bank accounts -> two Vendor rows; either should match."""
        vendor_a = self._make_vendor('"UNION TBK" MCHJ')
        vendor_b = self._make_vendor('"UNION TBK" MCHJ')
        expense = self._make_expense(vendor=vendor_b, doc_date=date(2026, 3, 10), amount="35000000.00")
        req = self._make_request(vendor_text=' "UNION TBK" MCHJ', amount="35000000.00", payed_date=date(2026, 3, 10))

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["linked"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)
        self.assertEqual(req.vendor_ref_id, vendor_b.id)
        self.assertNotEqual(vendor_a.id, vendor_b.id)

    def test_does_not_reclaim_already_claimed_expense(self):
        vendor = self._make_vendor("MAXSUSTRANS")
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="604650.00")
        already_linked = self._make_request(
            vendor_text="MAXSUSTRANS", amount="604650.00", payed_date=date(2026, 3, 10), title="Already linked",
        )
        Request.objects.filter(pk=already_linked.pk).update(
            expense_ref_id=expense.id, expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
        )
        other_req = self._make_request(
            vendor_text="MAXSUSTRANS", amount="604650.00", payed_date=date(2026, 3, 11), title="Should stay unlinked",
        )

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        outcomes = {r.request_id: r.outcome for r in results}
        self.assertEqual(outcomes[other_req.pk], "no_expense_match")
        other_req.refresh_from_db()
        self.assertIsNone(other_req.expense_ref_id)

    def test_does_not_touch_requests_that_already_have_vendor_ref(self):
        vendor = self._make_vendor("TASTIFY")
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="4000000.00")
        req = self._make_request(vendor_text="TASTIFY", amount="4000000.00", payed_date=date(2026, 3, 10))
        Request.objects.filter(pk=req.pk).update(vendor_ref_id=vendor.id)

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual(results, [])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_topup_payment_type_is_also_eligible(self):
        vendor = self._make_vendor("LEMONFIT2")
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="2000000.00")
        req = self._make_request(
            vendor_text="Lemonfit2", amount="2000000.00", payed_date=date(2026, 3, 10),
            payment_type=Request.PAYMENT_TYPE_TOPUP,
        )

        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual([r.outcome for r in results], ["linked"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)

    def test_leaves_system_comment_when_applied(self):
        vendor = self._make_vendor("SPORTOVAR")
        expense = self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="100000.00")
        req = self._make_request(vendor_text="Sportovar", amount="100000.00", payed_date=date(2026, 3, 10))

        find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        comments = list(RequestComment.objects.filter(request=req))
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].created_by_id, 1)
        self.assertIn(str(expense.id), comments[0].body)

    def test_dry_run_leaves_no_comment(self):
        vendor = self._make_vendor("SPORTOVAR")
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="100000.00")
        req = self._make_request(vendor_text="Sportovar", amount="100000.00", payed_date=date(2026, 3, 10))

        find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=False)

        self.assertFalse(RequestComment.objects.filter(request=req).exists())

    def test_idempotent_second_run_is_no_op(self):
        vendor = self._make_vendor("SPORTOVAR")
        self._make_expense(vendor=vendor, doc_date=date(2026, 3, 10), amount="100000.00")
        self._make_request(vendor_text="Sportovar", amount="100000.00", payed_date=date(2026, 3, 10))

        first = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)
        second = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=True)

        self.assertEqual([r.outcome for r in first], ["linked"])
        self.assertEqual(second, [])


class LinkLemonaquaTransferBankExpensesCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=LEMONAQUA_TENANT_ID, name="Lemonfit Aqua", subdomain="lemonaqua-cmd", is_active=True)
        self.admin = User.objects.create_user(username="admin-lemonaqua-cmd", password="x")
        if not User.objects.filter(pk=1).exists():
            User.objects.create_user(username="app", password="x", full_name="Система")
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        self.bank_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=bank_account,
        )

    def test_command_apply_writes_link(self):
        vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="MAXSUSTRANS", created_by=self.admin,
        )
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
            debit_turnover=Decimal("604650.00"),
            payment_purpose="x",
            vendor=vendor,
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
            billing_date=date(2026, 3, 1),
            vendor="MAXSUSTRANS",
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(date(2026, 3, 10)),
        )

        call_command("link_lemonaqua_transfer_bank_expenses", "--apply")

        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, expense.id)

    def test_command_without_apply_is_dry_run(self):
        vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="MAXSUSTRANS", created_by=self.admin,
        )
        BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 3, 10),
            process_date=date(2026, 3, 10),
            expense_year=2026,
            expense_month=3,
            expense_day=10,
            doc_no="",
            debit_turnover=Decimal("604650.00"),
            payment_purpose="x",
            vendor=vendor,
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
            billing_date=date(2026, 3, 1),
            vendor="MAXSUSTRANS",
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(date(2026, 3, 10)),
        )

        call_command("link_lemonaqua_transfer_bank_expenses")

        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)
