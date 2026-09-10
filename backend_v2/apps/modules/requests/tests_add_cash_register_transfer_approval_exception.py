"""
Tests for the `add_cash_register_transfer_approval_exception` one-time management command.

Covers:
  1. dry-run makes no changes
  2. --apply creates a single payment-step exception, copying the approver(s) and
     payment_action_mode from the tenant's default "Наличные" payment step
  3. re-running --apply is idempotent (no duplicate exception)
  4. a tenant whose purpose isn't configured yet is skipped
  5. a tenant whose default "Наличные" flow has no payment step is skipped
  6. a tenant whose payment step has no approvers is skipped
  7. --tenant limits the run to a single tenant
"""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from apps.modules.requests.models import (
    Approval,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant

User = get_user_model()
PURPOSE_NAME = "Перевод между кассами"


def _run(**options):
    out = StringIO()
    call_command("add_cash_register_transfer_approval_exception", stdout=out, **options)
    return out.getvalue()


class AddCashRegisterTransferApprovalExceptionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Lemonfit", subdomain="lemonfit", is_active=True)

        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant)
        form_pt_cash = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Наличные", is_enabled=True
        )
        self.purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=form_pt_cash, name=PURPOSE_NAME, category=PURPOSE_NAME
        )

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant)
        self.appr_pt_cash = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        self.payment_step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.appr_pt_cash,
            step=5,
            step_type=Approval.STEP_TYPE_PAYMENT,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE,
        )
        self.approver = User.objects.create_user(username="cashier1", password="x")
        RequestApprovalStepApproverConfig.objects.create(step_config=self.payment_step, approver_user=self.approver)

    def test_dry_run_makes_no_changes(self):
        _run()
        self.assertEqual(RequestApprovalPurposeExceptionPurpose.objects.count(), 0)

    def test_apply_creates_single_payment_step_exception_with_copied_approver(self):
        _run(apply=True)
        link = RequestApprovalPurposeExceptionPurpose.objects.get()
        self.assertEqual(link.payment_purpose_id, self.purpose.id)
        exception_config = link.exception_config
        self.assertEqual(exception_config.name, PURPOSE_NAME)

        steps = list(exception_config.steps.all())
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.step_type, Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(step.payment_action_mode, RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE)

        approvers = list(step.approvers.values_list("approver_user_id", flat=True))
        self.assertEqual(approvers, [self.approver.id])

    def test_apply_twice_is_idempotent(self):
        _run(apply=True)
        _run(apply=True)
        self.assertEqual(RequestApprovalPurposeExceptionPurpose.objects.count(), 1)

    def test_skips_tenant_without_purpose_configured(self):
        self.purpose.delete()
        _run(apply=True)
        self.assertEqual(RequestApprovalPurposeExceptionPurpose.objects.count(), 0)

    def test_skips_tenant_without_payment_step(self):
        self.payment_step.delete()
        _run(apply=True)
        self.assertEqual(RequestApprovalPurposeExceptionPurpose.objects.count(), 0)

    def test_skips_tenant_whose_payment_step_has_no_approvers(self):
        RequestApprovalStepApproverConfig.objects.filter(step_config=self.payment_step).delete()
        _run(apply=True)
        self.assertEqual(RequestApprovalPurposeExceptionPurpose.objects.count(), 0)

    def test_tenant_filter_limits_to_one_tenant(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        other_form_cfg = RequestFormConfig.objects.create(tenant=other)
        other_form_pt_cash = RequestFormPaymentTypeConfig.objects.create(
            config=other_form_cfg, payment_type="Наличные", is_enabled=True
        )
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=other_form_pt_cash, name=PURPOSE_NAME, category=PURPOSE_NAME
        )
        other_appr_cfg = RequestApprovalConfig.objects.create(tenant=other)
        other_appr_pt_cash = RequestApprovalPaymentTypeConfig.objects.create(
            config=other_appr_cfg, payment_type="Наличные", is_enabled=True
        )
        other_payment_step = RequestApprovalStepConfig.objects.create(
            payment_type_config=other_appr_pt_cash, step=5, step_type=Approval.STEP_TYPE_PAYMENT
        )
        other_approver = User.objects.create_user(username="other_cashier", password="x")
        RequestApprovalStepApproverConfig.objects.create(step_config=other_payment_step, approver_user=other_approver)

        _run(apply=True, tenant=self.tenant.id)

        self.assertTrue(
            RequestApprovalPurposeExceptionPurpose.objects.filter(payment_type_config=self.appr_pt_cash).exists()
        )
        self.assertFalse(
            RequestApprovalPurposeExceptionPurpose.objects.filter(payment_type_config=other_appr_pt_cash).exists()
        )
