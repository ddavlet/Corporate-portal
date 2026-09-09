"""
Tests for the "send approver on vacation / bring back" flow
(apps.modules.requests.user_approval_vacation + the
`toggle_user_approval_vacation` management command).

Scenario mirrors the real request: an approver who has `serial` (mandatory
approval) on one payment type and `notification` on another — vacation must
flip only the `serial` one, and returning must restore only what vacation
flipped.
"""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.requests.models import (
    Approval,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    UserApprovalVacation,
)
from apps.modules.requests.user_approval_vacation import (
    NoActiveVacation,
    VacationAlreadyActive,
    end_vacation,
    plan_vacation_start,
    start_vacation,
)
from apps.tenants.models import Tenant

User = get_user_model()


class UserApprovalVacationTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-vac", is_active=True)
        self.admin = User.objects.create_user(username="admin-vac", email="admin@acme.test", password="x")
        # Most real accounts have no email set — login identifier is `username`.
        self.sardor = User.objects.create_user(username="sardor", email="", password="x")

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)

        cash_pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        self.cash_step = RequestApprovalStepConfig.objects.create(
            payment_type_config=cash_pt, step=1, step_type=Approval.STEP_TYPE_SERIAL, is_enabled=True
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=self.cash_step, approver_user=self.sardor)

        transfer_pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Перечисление", is_enabled=True
        )
        self.transfer_step = RequestApprovalStepConfig.objects.create(
            payment_type_config=transfer_pt, step=1, step_type=Approval.STEP_TYPE_NOTIFICATION, is_enabled=True
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=self.transfer_step, approver_user=self.sardor)

        card_pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Платежная карта", is_enabled=True
        )
        self.payment_step = RequestApprovalStepConfig.objects.create(
            payment_type_config=card_pt, step=1, step_type=Approval.STEP_TYPE_PAYMENT, is_enabled=True
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=self.payment_step, approver_user=self.sardor)

    def _refresh(self, step_cfg):
        step_cfg.refresh_from_db()
        return step_cfg

    def test_plan_buckets_steps_by_current_step_type(self):
        plan = plan_vacation_start(tenant=self.tenant, user=self.sardor)

        self.assertEqual([ref.id for ref in plan.to_notify], [self.cash_step.id])
        self.assertEqual([ref.id for ref in plan.already_notification], [self.transfer_step.id])
        self.assertEqual([ref.id for ref in plan.skipped_payment], [self.payment_step.id])

    def test_start_vacation_switches_only_serial_step(self):
        vacation, plan = start_vacation(tenant=self.tenant, user=self.sardor)

        self.assertEqual(self._refresh(self.cash_step).step_type, Approval.STEP_TYPE_NOTIFICATION)
        self.assertEqual(self._refresh(self.transfer_step).step_type, Approval.STEP_TYPE_NOTIFICATION)
        self.assertEqual(self._refresh(self.payment_step).step_type, Approval.STEP_TYPE_PAYMENT)

        self.assertEqual(vacation.snapshot, [{"kind": UserApprovalVacation.KIND_STEP, "id": self.cash_step.id}])
        self.assertIsNone(vacation.ended_at)

    def test_start_vacation_twice_raises(self):
        start_vacation(tenant=self.tenant, user=self.sardor)

        with self.assertRaises(VacationAlreadyActive):
            start_vacation(tenant=self.tenant, user=self.sardor)

    def test_end_vacation_restores_only_the_flipped_step(self):
        start_vacation(tenant=self.tenant, user=self.sardor)

        vacation, result = end_vacation(tenant=self.tenant, user=self.sardor)

        self.assertEqual(self._refresh(self.cash_step).step_type, Approval.STEP_TYPE_SERIAL)
        self.assertEqual(self._refresh(self.transfer_step).step_type, Approval.STEP_TYPE_NOTIFICATION)
        self.assertEqual(self._refresh(self.payment_step).step_type, Approval.STEP_TYPE_PAYMENT)

        self.assertEqual([ref.id for ref in result.restored], [self.cash_step.id])
        self.assertEqual(result.skipped_changed, [])
        self.assertIsNotNone(vacation.ended_at)

    def test_end_vacation_without_active_vacation_raises(self):
        with self.assertRaises(NoActiveVacation):
            end_vacation(tenant=self.tenant, user=self.sardor)

    def test_end_vacation_skips_step_changed_manually_during_vacation(self):
        start_vacation(tenant=self.tenant, user=self.sardor)

        # Someone manually reverted it back to serial while the user was still on vacation.
        self.cash_step.step_type = Approval.STEP_TYPE_SERIAL
        self.cash_step.save(update_fields=["step_type"])

        vacation, result = end_vacation(tenant=self.tenant, user=self.sardor)

        self.assertEqual(result.restored, [])
        self.assertEqual([ref.id for ref in result.skipped_changed], [self.cash_step.id])
        self.assertIsNotNone(vacation.ended_at)

    def test_start_then_end_via_management_command(self):
        call_command(
            "toggle_user_approval_vacation",
            tenant=self.tenant.id,
            user=self.sardor.username,
            action="start",
            apply=True,
        )
        self.assertEqual(self._refresh(self.cash_step).step_type, Approval.STEP_TYPE_NOTIFICATION)
        self.assertTrue(UserApprovalVacation.objects.filter(tenant=self.tenant, user=self.sardor, ended_at__isnull=True).exists())

        call_command(
            "toggle_user_approval_vacation",
            tenant=self.tenant.id,
            user=self.sardor.username,
            action="end",
            apply=True,
        )
        self.assertEqual(self._refresh(self.cash_step).step_type, Approval.STEP_TYPE_SERIAL)
        self.assertFalse(UserApprovalVacation.objects.filter(tenant=self.tenant, user=self.sardor, ended_at__isnull=True).exists())

    def test_management_command_dry_run_does_not_change_anything(self):
        call_command(
            "toggle_user_approval_vacation",
            tenant=self.tenant.id,
            user=self.sardor.username,
            action="start",
        )

        self.assertEqual(self._refresh(self.cash_step).step_type, Approval.STEP_TYPE_SERIAL)
        self.assertFalse(UserApprovalVacation.objects.filter(tenant=self.tenant, user=self.sardor).exists())

    def test_management_command_unknown_user_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "toggle_user_approval_vacation",
                tenant=self.tenant.id,
                user="nobody",
                action="start",
                apply=True,
            )

    def test_management_command_falls_back_to_email_for_accounts_that_have_one(self):
        self.sardor.email = "sardor@acme.test"
        self.sardor.save(update_fields=["email"])

        call_command(
            "toggle_user_approval_vacation",
            tenant=self.tenant.id,
            user="sardor@acme.test",
            action="start",
            apply=True,
        )

        self.assertEqual(self._refresh(self.cash_step).step_type, Approval.STEP_TYPE_NOTIFICATION)
