"""Informational/service bank accounts never require approval requests."""

from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.bank_expense_reassignment import reassign_unmatched_bank_expenses
from apps.modules.requests.expense_compliance import (
    annotate_bank_expense_compliance,
    collect_bank_channel_payload,
    build_approval_rules_snapshot,
    filter_expenses_missing_request,
)
from apps.modules.requests.models import Request
from apps.modules.requests.request_required import is_request_required_for_expense
from apps.modules.wallets.resolution import (
    get_or_create_bank_wallet_for_account,
    get_or_create_corporate_wallet,
)
from apps.tenants.models import Tenant, TenantModuleConfig

User = get_user_model()

TRANSFER = Request.PAYMENT_TYPE_TRANSFER
ACC_CONTROLLED = "20208000000000000001"
ACC_INFO = "20208000000000000002"
ACC_SERVICE = "20208000000000000003"


class _Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(id=1, username="app", full_name="Система", password="x")
        self.tenant = Tenant.objects.create(name="AcctType One", subdomain="accttype-one", is_active=True)
        self.other = Tenant.objects.create(name="AcctType Two", subdomain="accttype-two", is_active=True)

    def _wallet(self, account_no, account_type, tenant=None):
        return get_or_create_bank_wallet_for_account(
            tenant=tenant or self.tenant, account_no=account_no, mfo="00000", account_type=account_type
        )

    def _expense(self, *, wallet, doc_no, tenant=None, amount="1000.00"):
        d = date(2026, 9, 15)
        return BankExpense.objects.create(
            tenant=tenant or self.tenant, created_by=self.user, row_no=0,
            doc_date=d, process_date=d, expense_year=2026, expense_month=9, expense_day=15,
            doc_no=doc_no, debit_turnover=Decimal(amount), payment_purpose=f"оплата {doc_no}",
            wallet=wallet,
        )


class RequestRequiredTests(_Base):
    def _required(self, expense):
        return is_request_required_for_expense(tenant=self.tenant, payment_type=TRANSFER, expense_obj=expense)

    def test_informational_and_service_expense_needs_no_request(self):
        for no, acc, kind in (("1", ACC_INFO, "informational"), ("2", ACC_SERVICE, "service")):
            e = self._expense(wallet=self._wallet(acc, kind), doc_no=no)
            self.assertFalse(self._required(e), kind)

    def test_controlled_expense_still_needs_request(self):
        e = self._expense(wallet=self._wallet(ACC_CONTROLLED, "controlled"), doc_no="1")
        self.assertTrue(self._required(e))

    def test_expense_without_wallet_or_bank_account_unchanged(self):
        unsaved = BankExpense(tenant=self.tenant, doc_no="1", payment_purpose="x")
        self.assertTrue(self._required(unsaved))
        walletless = SimpleNamespace(wallet=None, payment_purpose="x", payload={}, vendor=None)
        self.assertTrue(self._required(walletless))
        card_wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        card_expense = SimpleNamespace(wallet=card_wallet, payment_purpose="x", payload={}, vendor=None)
        self.assertTrue(self._required(card_expense))
        # Non-bank objects are never inspected, even if their wallet were an informational bank wallet.
        other_kind = SimpleNamespace(
            wallet=self._wallet(ACC_INFO, "informational"), payment_purpose="x", payload={}, vendor=None
        )
        self.assertTrue(self._required(other_kind))


class ComplianceTests(_Base):
    def setUp(self):
        super().setUp()
        self.controlled = self._expense(wallet=self._wallet(ACC_CONTROLLED, "controlled"), doc_no="1")
        self.info = self._expense(wallet=self._wallet(ACC_INFO, "informational"), doc_no="2", amount="2000.00")

    def test_missing_request_filter_skips_informational(self):
        qs = annotate_bank_expense_compliance(BankExpense.objects.all(), tenant=self.tenant)
        result = filter_expenses_missing_request(qs, tenant=self.tenant, payment_type=TRANSFER)
        self.assertEqual(list(result.values_list("pk", flat=True)), [self.controlled.pk])

    def test_channel_payload_skips_informational(self):
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="bank", is_enabled=True)
        payload = collect_bank_channel_payload(
            tenant=self.tenant,
            rules_by_pt=build_approval_rules_snapshot(tenant=self.tenant),
            date_from=None, date_to=None, limit=50,
        )
        self.assertEqual(payload["counts"]["missing_paid_request"], 1)


class BackfillAndReassignTests(_Base):
    def test_backfill_creates_no_request_for_informational(self):
        self._expense(wallet=self._wallet(ACC_INFO, "informational"), doc_no="1")
        out = StringIO()
        call_command("backfill_bank_expense_requests", "--tenant=accttype-one", "--apply", stdout=out)
        self.assertIn("Created: 0", out.getvalue())
        self.assertFalse(Request.all_objects.filter(tenant=self.tenant).exists())

    def test_reassignment_skips_informational(self):
        info = self._expense(wallet=self._wallet(ACC_INFO, "informational"), doc_no="57", amount="3000.00")
        controlled = self._expense(wallet=self._wallet(ACC_CONTROLLED, "controlled"), doc_no="58", amount="4000.00")
        for no, amount in (("57", "3000.00"), ("58", "4000.00")):
            Request.objects.create(
                tenant=self.other, created_by=self.user, title=f"Заявка {no}", amount=amount,
                currency="UZS", payment_type=TRANSFER, urgency=Request.URGENCY_NORMAL,
                billing_date=date(2026, 9, 1), status=Request.STATUS_PAYED,
                expense_id=no, expense_year=2026,
            )
        moved = reassign_unmatched_bank_expenses(tenant=self.tenant, other_tenant=self.other, created_by=self.user)
        info.refresh_from_db()
        controlled.refresh_from_db()
        self.assertEqual(info.tenant_id, self.tenant.id)
        self.assertEqual(controlled.tenant_id, self.other.id)
        self.assertEqual(len(moved), 1)
