"""Tests for the reusable backfill commands and their shared CLI options:
backfill_bank_expense_requests, backfill_cash_expense_requests,
backfill_card_expenses (requests.command_options)."""

from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.models import Request, RequestComment
from apps.modules.wallets.resolution import get_or_create_bank_wallet, get_or_create_cash_wallet
from apps.tenants.models import Tenant, TenantModuleConfig

User = get_user_model()


def _run(name, *args):
    out = StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


class _Base(TestCase):
    def setUp(self):
        self.system_user = User.objects.create_user(id=1, username="app", full_name="Система", password="x")
        self.t1 = Tenant.objects.create(name="Backfill One", subdomain="backfill-one", is_active=True)
        self.t2 = Tenant.objects.create(name="Backfill Two", subdomain="backfill-two", is_active=True)

    def _bank_expense(self, *, tenant, doc_date, doc_no, amount="1000.00"):
        return BankExpense.objects.create(
            tenant=tenant, created_by=self.system_user, row_no=0,
            doc_date=doc_date, process_date=doc_date,
            expense_year=doc_date.year, expense_month=doc_date.month, expense_day=doc_date.day,
            doc_no=doc_no, debit_turnover=Decimal(amount), payment_purpose=f"00599 оплата {doc_no}",
            wallet=get_or_create_bank_wallet(tenant=tenant),
        )


class TenantOptionTests(_Base):
    def test_requires_tenant_or_all_tenants(self):
        with self.assertRaises(CommandError):
            _run("backfill_bank_expense_requests")

    def test_tenant_and_all_tenants_are_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            _run("backfill_bank_expense_requests", "--tenant=backfill-one", "--all-tenants")

    def test_unknown_tenant_raises(self):
        with self.assertRaises(CommandError):
            _run("backfill_bank_expense_requests", "--tenant=nope")

    def test_invalid_date_range_raises(self):
        with self.assertRaises(CommandError):
            _run("backfill_bank_expense_requests", "--tenant=backfill-one",
                 "--date-from=2026-09-10", "--date-to=2026-09-01")

    def test_tenant_by_subdomain_and_id_and_all_tenants(self):
        self._bank_expense(tenant=self.t1, doc_date=date(2026, 9, 1), doc_no="1")
        self._bank_expense(tenant=self.t2, doc_date=date(2026, 9, 1), doc_no="2")

        self.assertIn("Would create: 1", _run("backfill_bank_expense_requests", "--tenant=backfill-one"))
        self.assertIn("Would create: 1", _run("backfill_bank_expense_requests", f"--tenant={self.t2.id}"))
        self.assertIn(
            "Would create: 2",
            _run("backfill_bank_expense_requests", "--tenant=backfill-one", "--tenant=backfill-two"),
        )
        # --all-tenants also covers other active tenants, so only check ours are included.
        out = _run("backfill_bank_expense_requests", "--all-tenants")
        self.assertIn("[backfill-one]", out)
        self.assertIn("[backfill-two]", out)


class BackfillBankExpenseRequestsTests(_Base):
    def test_dry_run_makes_no_changes(self):
        self._bank_expense(tenant=self.t1, doc_date=date(2026, 9, 1), doc_no="1")

        out = _run("backfill_bank_expense_requests", "--tenant=backfill-one")

        self.assertIn("Dry run complete", out)
        self.assertFalse(Request.all_objects.exists())

    def test_apply_respects_date_range_and_stores_payed_at_as_yyyymmdd(self):
        in_range = self._bank_expense(tenant=self.t1, doc_date=date(2026, 9, 15), doc_no="57")
        self._bank_expense(tenant=self.t1, doc_date=date(2026, 8, 31), doc_no="56")
        self._bank_expense(tenant=self.t1, doc_date=date(2026, 10, 1), doc_no="58")

        out = _run("backfill_bank_expense_requests", "--tenant=backfill-one",
                   "--date-from=2026-09-01", "--date-to=2026-09-30", "--apply")

        self.assertIn("Created: 1", out)
        req = Request.objects.get(tenant=self.t1)
        self.assertEqual(req.expense_ref_id, in_range.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)
        self.assertEqual(req.payed_at, 20260915)
        self.assertEqual(req.created_by_id, 1)
        self.assertTrue(RequestComment.objects.filter(request=req, created_by_id=1).exists())

    def test_expense_referenced_by_deleted_request_is_not_recreated(self):
        expense = self._bank_expense(tenant=self.t1, doc_date=date(2026, 9, 1), doc_no="1")
        Request.all_objects.create(
            tenant=self.t1, created_by=self.system_user, title="deleted", amount=Decimal("1000.00"),
            currency="UZS", payment_type=Request.PAYMENT_TYPE_TRANSFER, urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1), status=Request.STATUS_DELETED,
            expense_ref_id=expense.id, expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
        )

        out = _run("backfill_bank_expense_requests", "--tenant=backfill-one", "--apply")

        self.assertIn("Created: 0", out)

    def test_apply_is_idempotent(self):
        self._bank_expense(tenant=self.t1, doc_date=date(2026, 9, 1), doc_no="1")

        _run("backfill_bank_expense_requests", "--tenant=backfill-one", "--apply")
        out = _run("backfill_bank_expense_requests", "--tenant=backfill-one", "--apply")

        self.assertIn("Created: 0", out)
        self.assertEqual(Request.objects.filter(tenant=self.t1).count(), 1)


class BackfillCashExpenseRequestsTests(_Base):
    def _cash_expense(self, *, day: date, external_id: str):
        return CashExpense.objects.create(
            tenant=self.t1, external_id=external_id, title=f"Расход {external_id}", amount=Decimal("500.00"),
            currency="UZS", expense_at=timezone.make_aware(datetime(day.year, day.month, day.day, 12, 0)),
            expense_year=day.year, expense_month=day.month, expense_day=day.day,
            created_by=self.system_user, wallet=get_or_create_cash_wallet(tenant=self.t1, currency="UZS"),
        )

    def test_apply_respects_date_range_and_stores_payed_at_as_yyyymmdd(self):
        in_range = self._cash_expense(day=date(2026, 9, 5), external_id="c-1")
        self._cash_expense(day=date(2026, 8, 5), external_id="c-2")

        out = _run("backfill_cash_expense_requests", "--tenant=backfill-one", "--date-from=2026-09-01", "--apply")

        self.assertIn("Created: 1", out)
        req = Request.objects.get(tenant=self.t1)
        self.assertEqual(req.expense_ref_id, in_range.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CASH)
        self.assertEqual(req.payed_at, 20260905)
        self.assertEqual(req.billing_date, date(2026, 9, 1))
        self.assertTrue(RequestComment.objects.filter(request=req, created_by_id=1).exists())


class BackfillCardExpensesTests(_Base):
    def setUp(self):
        super().setUp()
        TenantModuleConfig.objects.create(tenant=self.t1, module_key="corporate_card", is_enabled=True)

    def _card_request(self, *, payed_at: int):
        return Request.objects.create(
            tenant=self.t1, created_by=self.system_user, requester=self.system_user, title="Карта",
            amount=Decimal("700.00"), currency="UZS", payment_type=Request.PAYMENT_TYPE_CARD,
            urgency=Request.URGENCY_NORMAL, billing_date=date(2026, 9, 1),
            status=Request.STATUS_PAYED, payed_at=payed_at,
        )

    def test_dry_run_filters_by_payed_at_range(self):
        in_range = self._card_request(payed_at=20260910)
        out_of_range = self._card_request(payed_at=20260810)

        out = _run("backfill_card_expenses", "--tenant=backfill-one", "--date-from=2026-09-01")

        self.assertIn(f"request id={in_range.id}", out)
        self.assertNotIn(f"request id={out_of_range.id}", out)
        self.assertIn("Would create: 1", out)
        self.assertFalse(CardExpense.objects.exists())

    def test_apply_creates_card_expense_and_comment(self):
        req = self._card_request(payed_at=20260910)

        out = _run("backfill_card_expenses", "--tenant=backfill-one", "--apply")

        req.refresh_from_db()
        self.assertIn("Created: 1", out)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD)
        self.assertTrue(CardExpense.objects.filter(pk=req.expense_ref_id, tenant=self.t1).exists())
        self.assertTrue(RequestComment.objects.filter(request=req, created_by_id=1).exists())
