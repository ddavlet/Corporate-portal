from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.modules.requests import payment_step_guards, status_events
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import (
    _recalculate_request_status,
    complete_request_payment_by_system,
    confirm_approval_by_id,
)
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
)
from apps.modules.telegram_approvals.services import dispatch_pending_approvals
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


def _suppress_all(*, request_obj):
    return "blocked for test"


def _rejected_handler_raises_integrity_error(*, request_obj):
    # Real DB-level constraint violation (unique subdomain), not a bare `raise
    # IntegrityError(...)`, so it actually aborts the DB connection's current
    # transaction the way a genuine handler bug would.
    Tenant.objects.create(name="Dup", subdomain=request_obj.tenant.subdomain, is_active=True)


class PaymentStepGuardTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Guard", subdomain="guard", is_active=True)
        self.approver = User.objects.create_user(username="guard-approver", password="x")
        self.payer = User.objects.create_user(username="guard-payer", password="x")
        for u in (self.approver, self.payer):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        # Approvals only get a Telegram recipient (approver_recipient_id) when the
        # approver user has telegram_chat_id set (approval_bootstrap.py:36-37). Set
        # this before create_approval_rows_for_request so dispatch tests actually
        # exercise the send path instead of being filtered out earlier for an
        # unrelated reason (approver_recipient_id__isnull=False).
        self.approver.telegram_chat_id = 111
        self.approver.save(update_fields=["telegram_chat_id"])
        self.payer.telegram_chat_id = 222
        self.payer.save(update_fields=["telegram_chat_id"])
        cfg = RequestApprovalConfig.objects.create(tenant=self.tenant)
        pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=cfg, payment_type=Request.PAYMENT_TYPE_PAYROLL, is_enabled=True
        )
        s1 = RequestApprovalStepConfig.objects.create(payment_type_config=pt, step=1, is_enabled=True)
        RequestApprovalStepApproverConfig.objects.create(step_config=s1, approver_user=self.approver)
        s2 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt, step=2, is_enabled=True, step_type=Approval.STEP_TYPE_PAYMENT
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=s2, approver_user=self.payer)
        self.req = Request.objects.create(
            tenant=self.tenant, created_by=self.approver, requester=self.approver, title="t",
            amount="100.00", payment_type=Request.PAYMENT_TYPE_PAYROLL, status=Request.STATUS_DRAFT,
            billing_date=timezone.localdate(),
        )
        create_approval_rows_for_request(self.req)
        _recalculate_request_status(self.req)
        self._saved_suppressors = payment_step_guards.PAYMENT_STEP_SUPPRESSORS
        self._saved_rejected = status_events.REQUEST_REJECTED_EVENT_HANDLERS
        # Task 5 (payroll) registers its own suppressor/handler in PayrollConfig.ready();
        # these requests aren't linked to a payroll document so they'd no-op anyway, but
        # start from a clean registry to keep this test file self-contained.
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = ()
        status_events.REQUEST_REJECTED_EVENT_HANDLERS = ()

    def tearDown(self):
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = self._saved_suppressors
        status_events.REQUEST_REJECTED_EVENT_HANDLERS = self._saved_rejected

    def _approve_step1(self):
        a1 = Approval.objects.get(request=self.req, step=1)
        with patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None):
            confirm_approval_by_id(tenant=self.tenant, approval_id=a1.id, approver_user_id=self.approver.id)
        self.req.refresh_from_db()

    def test_suppressed_payment_step_cannot_be_confirmed_manually(self):
        payment_step_guards.register_payment_step_suppressor(_suppress_all)
        self._approve_step1()
        self.assertEqual(self.req.status, Request.STATUS_APPROVED)
        pay = Approval.objects.get(request=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        with self.assertRaises(ValidationError):
            confirm_approval_by_id(tenant=self.tenant, approval_id=pay.id, approver_user_id=self.payer.id)

    @patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
    def test_suppressed_payment_step_not_dispatched(self, send_mock):
        payment_step_guards.register_payment_step_suppressor(_suppress_all)
        self._approve_step1()
        send_mock.reset_mock()
        sent = dispatch_pending_approvals(request_obj=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(sent, 0)
        send_mock.assert_not_called()

    @patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None)
    def test_without_suppressor_payment_step_dispatched_to_telegram(self, send_mock):
        # Control test for the above: with no suppressor registered, the payment
        # approval is not excluded from approvals_qs and TelegramDispatcher.send is
        # actually attempted. The mock returns None, which the dispatcher code
        # treats as "gateway unreachable" (services.py ~687-689) and does not count
        # as sent, but the call itself must have happened.
        self._approve_step1()
        send_mock.reset_mock()
        pay = Approval.objects.get(request=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        sent = dispatch_pending_approvals(request_obj=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(sent, 0)
        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.kwargs["approval_id"], pay.id)

    def test_complete_by_system_marks_payed(self):
        payment_step_guards.register_payment_step_suppressor(_suppress_all)
        self._approve_step1()
        with patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None):
            status = complete_request_payment_by_system(request_obj=self.req, comment="Выплачено")
        self.assertEqual(status, Request.STATUS_PAYED)
        self.req.refresh_from_db()
        self.assertIsNotNone(self.req.payed_at)
        pay = Approval.objects.get(request=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(pay.decision, Approval.DECISION_APPROVED)
        self.assertEqual(pay.comment, "Выплачено")

    def test_complete_by_system_requires_approved(self):
        with self.assertRaises(ValidationError):
            complete_request_payment_by_system(request_obj=self.req, comment="x")

    def test_rejected_handler_called_once_on_reject(self):
        calls = []
        status_events.register_request_rejected_event_handler(lambda *, request_obj: calls.append(request_obj.id))
        a1 = Approval.objects.get(request=self.req, step=1)
        with patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None):
            confirm_approval_by_id(
                tenant=self.tenant, approval_id=a1.id, approver_user_id=self.approver.id,
                decision=Approval.DECISION_REJECTED,
            )
        self.assertEqual(calls, [self.req.id])

    def test_rejected_handler_integrity_error_does_not_block_rejection(self):
        status_events.register_request_rejected_event_handler(_rejected_handler_raises_integrity_error)
        a1 = Approval.objects.get(request=self.req, step=1)
        with patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None):
            # Must not raise IntegrityError / TransactionManagementError to the caller:
            # the failing handler runs in its own savepoint (status_events.py).
            confirm_approval_by_id(
                tenant=self.tenant, approval_id=a1.id, approver_user_id=self.approver.id,
                decision=Approval.DECISION_REJECTED,
            )
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_REJECTED)

    def test_without_suppressor_payment_step_confirmable(self):
        self._approve_step1()
        pay = Approval.objects.get(request=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        with patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None):
            confirm_approval_by_id(tenant=self.tenant, approval_id=pay.id, approver_user_id=self.payer.id)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_PAYED)


class PaymentWebappConfirmSuppressionTests(APITestCase):
    """
    Endpoint-level coverage for `approvals_payment_webapp_confirm`: a suppressed
    payment step must be rejected before any expense fields are persisted on the
    Request (views.py writes expense_id/expense_ref_id/expense_ref_target and
    saves before calling confirm_approval_by_id, so the suppression check has to
    happen earlier, right after the step_type == payment check).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(name="GuardApi", subdomain="guardapi", is_active=True)
        self.approver = User.objects.create_user(username="guardapi-approver", password="x")
        self.payer = User.objects.create_user(username="guardapi-payer", password="x")
        for u in (self.approver, self.payer):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
            TenantUserRole.objects.create(tenant=self.tenant, user=u, role=TenantUserRole.ROLE_APPROVER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "guardapi.example.com"

        cfg = RequestApprovalConfig.objects.create(tenant=self.tenant)
        pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=cfg, payment_type=Request.PAYMENT_TYPE_PAYROLL, is_enabled=True
        )
        s1 = RequestApprovalStepConfig.objects.create(payment_type_config=pt, step=1, is_enabled=True)
        RequestApprovalStepApproverConfig.objects.create(step_config=s1, approver_user=self.approver)
        s2 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt,
            step=2,
            is_enabled=True,
            step_type=Approval.STEP_TYPE_PAYMENT,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=s2, approver_user=self.payer)

        self.req = Request.objects.create(
            tenant=self.tenant, created_by=self.approver, requester=self.approver, title="t",
            amount="100.00", payment_type=Request.PAYMENT_TYPE_PAYROLL, status=Request.STATUS_DRAFT,
            billing_date=timezone.localdate(),
        )
        create_approval_rows_for_request(self.req)
        _recalculate_request_status(self.req)

        self._saved_suppressors = payment_step_guards.PAYMENT_STEP_SUPPRESSORS
        self._saved_rejected = status_events.REQUEST_REJECTED_EVENT_HANDLERS
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = ()
        status_events.REQUEST_REJECTED_EVENT_HANDLERS = ()

    def tearDown(self):
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = self._saved_suppressors
        status_events.REQUEST_REJECTED_EVENT_HANDLERS = self._saved_rejected

    def test_suppressed_payment_step_webapp_confirm_returns_400_without_persisting_expense(self):
        payment_step_guards.register_payment_step_suppressor(_suppress_all)
        a1 = Approval.objects.get(request=self.req, step=1)
        with patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None):
            confirm_approval_by_id(tenant=self.tenant, approval_id=a1.id, approver_user_id=self.approver.id)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_APPROVED)
        self.assertIsNone(self.req.expense_id)

        pay = Approval.objects.get(request=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.client.force_authenticate(self.payer)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": pay.id, "expense_id": "INV-1"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)

        self.req.refresh_from_db()
        pay.refresh_from_db()
        self.assertIsNone(self.req.expense_id)
        self.assertIsNone(self.req.expense_ref_id)
        self.assertEqual(pay.decision, Approval.DECISION_PENDING)
