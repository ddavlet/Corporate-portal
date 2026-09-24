import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.cashier.models import CashExpense
from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine, PayrollPayout
from apps.modules.payroll.payouts import close_underpaid, create_payout_expense, payout_state
from apps.modules.payroll.services import accept_document, create_draft_document
from apps.modules.payroll.tests_workflow import make_payroll_approval_chain
from apps.modules.requests.approval_workflow import confirm_approval_by_id
from apps.modules.requests.models import Approval, Request, RequestComment
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig

User = get_user_model()


@patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None)
class PayrollPayoutTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Pay", subdomain="pay", is_active=True, payroll_payout_mode=Tenant.PAYROLL_PAYOUT_MODE_PORTAL
        )
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        self.system = User.objects.filter(pk=1).first() or User.objects.create_user(id=1, username="system", password="x")
        self.user = User.objects.create_user(username="pay-user", password="x")
        self.approver = User.objects.create_user(username="pay-approver", password="x")
        self.payer = User.objects.create_user(username="pay-payer", password="x")
        for u in (self.approver, self.payer):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        make_payroll_approval_chain(self.tenant, self.approver, payer=self.payer)
        self.alice = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        self.bob = Employee.objects.create(tenant=self.tenant, full_name="Bob")
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        self.day = datetime.date(2026, 9, 30)

    def _approved_doc(self):
        doc = create_draft_document(
            tenant=self.tenant, user=self.user, period_month=datetime.date(2026, 9, 1), kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("700")}, {"employee": self.bob, "sum": Decimal("300")}],
        )
        req = accept_document(document=doc, actor=self.user)
        a1 = Approval.objects.get(request=req, step=1)
        confirm_approval_by_id(tenant=self.tenant, approval_id=a1.id, approver_user_id=self.approver.id)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_APPROVED)
        doc.refresh_from_db()
        return doc, req

    def _pay(self, doc, items):
        return create_payout_expense(
            document=doc, wallet_id=self.wallet.id, date=self.day,
            items=[{"employee_id": e.id, "amount": Decimal(a)} for e, a in items], actor=self.user,
        )

    def test_partial_then_full_payout_marks_request_payed(self, _tg):
        doc, req = self._approved_doc()
        exp1 = self._pay(doc, [(self.alice, "500"), (self.bob, "300")])
        self.assertEqual(exp1.amount, Decimal("800.00"))
        self.assertEqual(exp1.wallet_id, self.wallet.id)
        # Compared in local time (Asia/Tashkent): the aware datetime is built from
        # `date` + current local time-of-day, so its calendar date must be read back
        # via timezone.localtime() rather than the raw (possibly UTC-shifted) value.
        self.assertEqual(timezone.localtime(exp1.expense_at).date(), self.day)
        state = payout_state(doc)
        self.assertEqual(state["remaining_total"], Decimal("200.00"))
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_APPROVED)

        self._pay(doc, [(self.alice, "200")])
        req.refresh_from_db()
        doc.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.amount, Decimal("1000.00"))
        self.assertEqual(doc.status, PayrollDocument.STATUS_CLOSED)
        self.assertTrue(RequestComment.objects.filter(request=req, body__contains=f"№{doc.pk}").exists())
        self.assertEqual(PayrollPayout.objects.filter(document=doc).count(), 3)

    def test_second_payout_sees_first_and_is_limited(self, _tg):
        doc, _ = self._approved_doc()
        self._pay(doc, [(self.alice, "600")])
        with self.assertRaises(ValidationError):
            self._pay(doc, [(self.alice, "101")])
        self._pay(doc, [(self.alice, "100")])

    def test_rejects_foreign_employee_duplicate_and_non_positive(self, _tg):
        doc, _ = self._approved_doc()
        carol = Employee.objects.create(tenant=self.tenant, full_name="Carol")
        for items in ([(carol, "1")], [(self.alice, "1"), (self.alice, "1")], [(self.alice, "0")], []):
            with self.assertRaises(ValidationError):
                self._pay(doc, items)
        self.assertFalse(CashExpense.objects.filter(tenant=self.tenant).exists())

    def test_payout_state_reports_request_not_approved(self, _tg):
        doc = create_draft_document(
            tenant=self.tenant, user=self.user, period_month=datetime.date(2026, 9, 1), kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("1")}],
        )
        accept_document(document=doc, actor=self.user)
        doc.refresh_from_db()
        state = payout_state(doc)
        self.assertFalse(state["can_pay"])
        self.assertIn("не согласована", state["reason"])
        with self.assertRaises(ValidationError):
            self._pay(doc, [(self.alice, "1")])

    def test_legacy_mode_blocks_payouts(self, _tg):
        doc, _ = self._approved_doc()
        PayrollDocument.objects.filter(pk=doc.pk).update(payout_mode=PayrollDocument.PAYOUT_MODE_LEGACY)
        doc.refresh_from_db()
        self.assertFalse(payout_state(doc)["can_pay"])
        with self.assertRaises(ValidationError):
            self._pay(doc, [(self.alice, "1")])

    def test_cash_module_disabled_blocks_payouts(self, _tg):
        doc, _ = self._approved_doc()
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="cash").update(is_enabled=False)
        with self.assertRaises(ValidationError):
            self._pay(doc, [(self.alice, "1")])

    def test_payout_blocked_when_line_without_employee(self, _tg):
        doc, _ = self._approved_doc()
        PayrollLine.objects.create(document=doc, line_no=99, employee="Ghost", item="x", sum="0.01")
        state = payout_state(doc)
        self.assertFalse(state["can_pay"])
        self.assertIn("без сотрудника", state["reason"])

    def test_payout_rejects_non_uzs_cash_register(self, _tg):
        doc, _ = self._approved_doc()
        usd_wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="USD")
        with self.assertRaises(ValidationError):
            create_payout_expense(
                document=doc, wallet_id=usd_wallet.id, date=self.day,
                items=[{"employee_id": self.alice.id, "amount": Decimal("1")}], actor=self.user,
            )

    def test_n8n_document_limit_is_sum_of_employee_lines(self, _tg):
        doc, req = self._approved_doc()
        PayrollLine.objects.create(document=doc, line_no=3, employee="Alice", employee_fk=self.alice, item="Премия", sum="50")
        # request amount no longer equals lines total, but limit logic must use lines per employee
        state = payout_state(doc)
        alice_row = next(r for r in state["employees"] if r["employee_id"] == self.alice.id)
        self.assertEqual(alice_row["accrued"], Decimal("750.00"))

    def test_close_underpaid(self, _tg):
        doc, req = self._approved_doc()
        self._pay(doc, [(self.alice, "100")])
        with self.assertRaises(ValidationError):
            close_underpaid(document=doc, actor=self.user, comment="  ")
        close_underpaid(document=doc, actor=self.user, comment="Bob уволился")
        doc.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.amount, Decimal("1000.00"))
        self.assertEqual(doc.status, PayrollDocument.STATUS_CLOSED)
        self.assertIsNotNone(doc.closed_underpaid_at)
        self.assertEqual(doc.closed_by, self.user)
        self.assertEqual(doc.close_comment, "Bob уволился")
        pay = Approval.objects.get(request=req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertIn("недоплат", pay.comment)

    def test_cash_expense_with_payouts_cannot_be_deleted(self, _tg):
        doc, _ = self._approved_doc()
        exp = self._pay(doc, [(self.alice, "1")])
        with self.assertRaises(ProtectedError):
            exp.delete()
