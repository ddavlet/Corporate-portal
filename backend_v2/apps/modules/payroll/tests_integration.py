"""
Final-review fix wave (I2, I4, M5, M6) — end-to-end coverage that exercises the real
registrations PayrollConfig.ready() wires into apps.modules.requests.payment_step_guards
/ status_events, instead of swapping in fake suppressors/handlers like
requests/tests_payment_step_guards.py does. If PayrollConfig.ready() ever stops
registering these hooks (or registers the wrong function), these tests fail even
though the hook unit itself is untouched.
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.cashier.models import CashExpense
from apps.modules.payroll.constants import PORTAL_PAYOUT_BLOCK_REASON
from apps.modules.payroll.hooks import revert_document_to_draft_on_reject
from apps.modules.payroll.models import Employee, PayrollDocument, PayrollPayout
from apps.modules.payroll.services import accept_document, cancel_draft_document, create_draft_document
from apps.modules.payroll.tests_workflow import make_payroll_approval_chain
from apps.modules.requests.approval_workflow import confirm_approval_by_id
from apps.modules.requests.expense_compliance import build_approval_rules_snapshot, collect_payroll_channel_payload
from apps.modules.requests.models import Approval, Request, RequestComment
from apps.modules.telegram_approvals.services import dispatch_pending_approvals
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig

User = get_user_model()


@patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None)
class PayrollSuppressorEndToEndTests(TestCase):
    """I4: real suppressor/handler, no fakes — covers the portal-mode block and the
    legacy-mode control case through the actual accept -> approve step1 -> confirm
    payment step pipeline."""

    def _setup_tenant(self, *, payout_mode, tag):
        tenant = Tenant.objects.create(
            name=f"E2E-{tag}", subdomain=f"e2e-payroll-{tag}", is_active=True, payroll_payout_mode=payout_mode
        )
        TenantModuleConfig.objects.create(tenant=tenant, module_key="payroll", is_enabled=True)
        user = User.objects.create_user(username=f"e2e-user-{tag}", password="x")
        approver = User.objects.create_user(username=f"e2e-approver-{tag}", password="x")
        payer = User.objects.create_user(username=f"e2e-payer-{tag}", password="x")
        for u in (approver, payer):
            TenantMembership.objects.create(tenant=tenant, user=u, is_active=True)
        # Approver_recipient_id on the Approval row is snapshotted from telegram_chat_id
        # at create_approval_rows_for_request time, so this must be set before accept_
        # document (which triggers that call) — otherwise the pending-approver filter
        # elsewhere would mask the payment step's Telegram dispatch for an unrelated
        # reason and the "not called" assertion below would be meaningless.
        payer.telegram_chat_id = 999
        payer.save(update_fields=["telegram_chat_id"])
        make_payroll_approval_chain(tenant, approver, payer=payer)
        employee = Employee.objects.create(tenant=tenant, full_name="Alice")
        doc = create_draft_document(
            tenant=tenant, user=user, period_month=datetime.date(2026, 9, 1), kind="salary",
            lines_data=[{"employee": employee, "sum": Decimal("100")}],
        )
        req = accept_document(document=doc, actor=user)
        doc.refresh_from_db()
        a1 = Approval.objects.get(request=req, step=1)
        confirm_approval_by_id(tenant=tenant, approval_id=a1.id, approver_user_id=approver.id)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_APPROVED)
        return tenant, doc, req, payer

    def test_portal_mode_payment_step_blocked_end_to_end(self, send_mock):
        tenant, doc, req, payer = self._setup_tenant(payout_mode=Tenant.PAYROLL_PAYOUT_MODE_PORTAL, tag="portal")
        self.assertEqual(doc.payout_mode, PayrollDocument.PAYOUT_MODE_PORTAL)
        pay = Approval.objects.get(request=req, step_type=Approval.STEP_TYPE_PAYMENT)

        send_mock.reset_mock()
        sent = dispatch_pending_approvals(request_obj=req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(sent, 0)
        send_mock.assert_not_called()

        with self.assertRaises(ValidationError) as ctx:
            confirm_approval_by_id(tenant=tenant, approval_id=pay.id, approver_user_id=payer.id)
        self.assertIn(PORTAL_PAYOUT_BLOCK_REASON, str(ctx.exception))
        pay.refresh_from_db()
        self.assertEqual(pay.decision, Approval.DECISION_PENDING)
        send_mock.assert_not_called()

    def test_legacy_mode_payment_step_confirms_to_payed(self, send_mock):
        tenant, doc, req, payer = self._setup_tenant(payout_mode=Tenant.PAYROLL_PAYOUT_MODE_LEGACY, tag="legacy")
        self.assertEqual(doc.payout_mode, PayrollDocument.PAYOUT_MODE_LEGACY)
        pay = Approval.objects.get(request=req, step_type=Approval.STEP_TYPE_PAYMENT)
        confirm_approval_by_id(tenant=tenant, approval_id=pay.id, approver_user_id=payer.id)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_PAYED)

    def test_module_disabled_payment_step_falls_back_to_normal_flow(self, send_mock):
        """M5: graceful degradation — a disabled payroll module must not leave a
        portal-mode payment step permanently unconfirmable."""
        tenant, doc, req, payer = self._setup_tenant(payout_mode=Tenant.PAYROLL_PAYOUT_MODE_PORTAL, tag="disabled")
        TenantModuleConfig.objects.filter(tenant=tenant, module_key="payroll").update(is_enabled=False)
        pay = Approval.objects.get(request=req, step_type=Approval.STEP_TYPE_PAYMENT)
        confirm_approval_by_id(tenant=tenant, approval_id=pay.id, approver_user_id=payer.id)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_PAYED)


class RevertHookAndCancelPayoutGuardTests(TestCase):
    """M6: a document with real payouts against it must never be silently reverted to
    draft (or cancelled), regardless of how a REJECTED Request reaches the hook."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="RevertGuard", subdomain="revert-guard", is_active=True)
        self.user = User.objects.create_user(username="revert-guard-user", password="x")
        self.employee = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")

    def _cash_expense(self, external_id):
        now = timezone.now()
        return CashExpense.objects.create(
            tenant=self.tenant, external_id=external_id, amount=Decimal("10"), expense_at=now,
            expense_year=now.year, expense_month=now.month, expense_day=now.day,
            created_by=self.user, wallet=self.wallet,
        )

    def test_revert_hook_does_not_revert_accepted_document_with_payouts(self):
        doc = PayrollDocument.objects.create(
            tenant=self.tenant, source=PayrollDocument.SOURCE_PORTAL,
            payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL, status=PayrollDocument.STATUS_ACCEPTED,
        )
        req = Request.objects.create(
            tenant=self.tenant, created_by=self.user, requester=self.user, title="t", amount="100.00",
            payment_type=Request.PAYMENT_TYPE_PAYROLL, status=Request.STATUS_REJECTED,
            billing_date=timezone.localdate(),
            expense_ref_id=doc.pk, expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
        )
        PayrollPayout.objects.create(
            tenant=self.tenant, document=doc, employee=self.employee,
            cash_expense=self._cash_expense("zp-revert-guard-1"), amount=Decimal("10"),
        )

        revert_document_to_draft_on_reject(request_obj=req)

        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertFalse(RequestComment.objects.filter(request=req).exists())

    def test_cancel_draft_document_refuses_when_payouts_exist(self):
        # Payouts normally require STATUS_ACCEPTED (payouts._blocked_reason), so a
        # DRAFT document with payouts shouldn't occur via the public API post-fix —
        # this exercises the defensive guard in cancel_draft_document directly.
        doc = PayrollDocument.objects.create(
            tenant=self.tenant, source=PayrollDocument.SOURCE_PORTAL,
            payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL, status=PayrollDocument.STATUS_DRAFT,
        )
        PayrollPayout.objects.create(
            tenant=self.tenant, document=doc, employee=self.employee,
            cash_expense=self._cash_expense("zp-revert-guard-2"), amount=Decimal("5"),
        )
        with self.assertRaises(ValidationError):
            cancel_draft_document(document=doc)
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_DRAFT)


class PayrollComplianceChannelExcludesDraftAndCancelledTests(TestCase):
    """I2: collect_payroll_channel_payload must not treat drafts/cancelled drafts as
    "missing paid request" forever."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Compliance", subdomain="compliance-payroll", is_active=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
        self.user = User.objects.create_user(username="compliance-user", password="x")
        self.employee = Employee.objects.create(tenant=self.tenant, full_name="Alice")

    def _draft(self):
        return create_draft_document(
            tenant=self.tenant, user=self.user, period_month=datetime.date(2026, 9, 1), kind="salary",
            lines_data=[{"employee": self.employee, "sum": Decimal("10")}],
        )

    def test_draft_and_cancelled_documents_excluded_from_unmatched_payroll_payload(self):
        draft = self._draft()
        cancelled = self._draft()
        cancel_draft_document(document=cancelled)

        rules_by_pt = build_approval_rules_snapshot(tenant=self.tenant)
        payload = collect_payroll_channel_payload(
            tenant=self.tenant, rules_by_pt=rules_by_pt, date_from=None, date_to=None, limit=500
        )
        ids = {row["id"] for row in payload["missing_paid_request"]}
        self.assertNotIn(draft.pk, ids)
        self.assertNotIn(cancelled.pk, ids)
