from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.exceptions import ValidationError

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
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()


def _suppress_all(*, request_obj):
    return "blocked for test"


class PaymentStepGuardTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Guard", subdomain="guard", is_active=True)
        self.approver = User.objects.create_user(username="guard-approver", password="x")
        self.payer = User.objects.create_user(username="guard-payer", password="x")
        for u in (self.approver, self.payer):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
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
        )
        create_approval_rows_for_request(self.req)
        _recalculate_request_status(self.req)
        self._saved_suppressors = payment_step_guards.PAYMENT_STEP_SUPPRESSORS
        self._saved_rejected = status_events.REQUEST_REJECTED_EVENT_HANDLERS

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

    def test_without_suppressor_payment_step_confirmable(self):
        self._approve_step1()
        pay = Approval.objects.get(request=self.req, step_type=Approval.STEP_TYPE_PAYMENT)
        with patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None):
            confirm_approval_by_id(tenant=self.tenant, approval_id=pay.id, approver_user_id=self.payer.id)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_PAYED)
