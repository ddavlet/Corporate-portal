"""
Tests for clone_tenant_config: copying a branch's configuration into a new
tenant without its data, never overwriting what the target already has.
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.cash_withdrawals.models import CashWithdrawalConfig, CashWithdrawalConfirmer
from apps.modules.investments.models import (
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentFormConfig,
    InvestNotificationConfig,
)
from apps.modules.reports.models import TenantReportSettings
from apps.modules.requests.models import (
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestApprovalPurposeExceptionStepApproverConfig,
    RequestApprovalPurposeExceptionStepConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestCategory,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestPaymentPurposeConfig,
)
from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.tenants.config_clone import clone_tenant_config
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

CASH = Request.PAYMENT_TYPE_CASH


class CloneTenantConfigTests(TestCase):
    def setUp(self):
        self.source = Tenant.objects.create(
            name="Club Havo", subdomain="clone-src", is_active=True, payroll_payout_mode=Tenant.PAYROLL_PAYOUT_MODE_PORTAL,
        )
        other = Tenant.objects.create(name="Club One", subdomain="clone-other", is_active=True)
        self.admin = User.objects.create_user(username="clone-admin", password="x")
        self.approver = User.objects.create_user(username="clone-approver", password="x")
        self.requester = User.objects.create_user(username="clone-requester", password="x")
        for user, role in ((self.admin, "admin"), (self.approver, "approver"), (self.requester, "requester")):
            TenantMembership.objects.create(tenant=self.source, user=user, is_active=True)
            TenantUserRole.objects.create(tenant=self.source, user=user, role=role)

        for key, enabled in (("requests", True), ("cash", True), ("tasks", False), ("telegram_approvals", True)):
            TenantModuleConfig.objects.create(tenant=self.source, module_key=key, is_enabled=enabled)

        self.shared_chat = TenantTelegramChat.objects.create(tenant=self.source, name="Бухгалтерия", chat_id="-100")
        TenantTelegramChat.objects.create(tenant=other, name="Бухгалтерия", chat_id="-100")
        self.branch_chat = TenantTelegramChat.objects.create(tenant=self.source, name="Касса Havo", chat_id="-200")

        RequestCategory.objects.create(tenant=self.source, name="Содержание клуба", is_active=True)
        RequestCategory.objects.create(tenant=self.source, name="Старая", is_active=False)
        form = RequestFormConfig.objects.create(tenant=self.source)
        cash_form = RequestFormPaymentTypeConfig.objects.create(
            config=form, payment_type=CASH, default_company_payer="Club HAVO",
        )
        self.repair = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=cash_form, name="Ремонтные работы", category="Содержание клуба",
        )
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=cash_form, name="Видеограф", category="Содержание клуба", is_active=False,
        )
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=cash_form, user=self.requester)

        approval_pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=RequestApprovalConfig.objects.create(tenant=self.source), payment_type=CASH,
        )
        step1 = RequestApprovalStepConfig.objects.create(payment_type_config=approval_pt, step=1)
        RequestApprovalStepApproverConfig.objects.create(step_config=step1, approver_user=self.approver)
        step2 = RequestApprovalStepConfig.objects.create(
            payment_type_config=approval_pt,
            step=2,
            step_type="payment",
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
            payment_webapp_url="https://t.me/havo_bot/payment",
            telegram_chat=self.shared_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step2, approver_user=self.admin)
        exception = RequestApprovalPurposeExceptionConfig.objects.create(payment_type_config=approval_pt, name="Ремонт")
        RequestApprovalPurposeExceptionPurpose.objects.create(exception_config=exception, payment_purpose=self.repair)
        exc_step = RequestApprovalPurposeExceptionStepConfig.objects.create(exception_config=exception, step=1)
        RequestApprovalPurposeExceptionStepApproverConfig.objects.create(step_config=exc_step, approver_user=self.approver)

        InvestmentFormConfig.objects.create(tenant=self.source, uses_companies=False, allowed_return_types=["дивиденды"])
        inv = InvestmentApprovalConfig.objects.create(tenant=self.source, is_enabled=True)
        inv_step = InvestmentApprovalConfigStep.objects.create(config=inv, step=1, telegram_chat=self.branch_chat)
        InvestmentApprovalConfigStepApprover.objects.create(step=inv_step, approver_user=self.approver)
        InvestNotificationConfig.objects.create(tenant=self.source, responsible_user=self.admin)

        TenantReportSettings.objects.create(tenant=self.source, pnl_source="backend", pnl_config={"start_month": "2026-01"})
        cw = CashWithdrawalConfig.objects.create(tenant=self.source, is_active=True, card_telegram_chat=self.branch_chat)
        CashWithdrawalConfirmer.objects.create(config=cw, user=self.admin)

    def _clone(self, *, with_members=True, apply_changes=True, name="Club NEW"):
        return clone_tenant_config(
            source=self.source, target_subdomain="clone-new", target_name=name,
            with_members=with_members, apply_changes=apply_changes,
        )

    def test_dry_run_creates_nothing(self):
        report = self._clone(apply_changes=False)

        self.assertTrue(report.changes)
        self.assertFalse(Tenant.objects.filter(subdomain="clone-new").exists())

    def test_apply_with_members_copies_configuration_but_not_data(self):
        Tenant.objects.create(name="Club NEW", subdomain="clone-new", is_active=True, telegram_bot_username="new_bot")

        report = self._clone()
        target = Tenant.objects.get(subdomain="clone-new")

        self.assertEqual(target.payroll_payout_mode, Tenant.PAYROLL_PAYOUT_MODE_PORTAL)
        self.assertEqual(
            set(TenantModuleConfig.objects.filter(tenant=target, is_enabled=True).values_list("module_key", flat=True)),
            {"requests", "cash"},
        )
        self.assertEqual(
            set(TenantUserRole.objects.filter(tenant=target).values_list("user_id", "role")),
            {(self.admin.pk, "admin"), (self.approver.pk, "approver"), (self.requester.pk, "requester")},
        )
        self.assertEqual(
            list(RequestCategory.objects.filter(tenant=target).values_list("name", flat=True)), ["Содержание клуба"],
        )

        cash_form = RequestFormPaymentTypeConfig.objects.get(config__tenant=target, payment_type=CASH)
        self.assertEqual(cash_form.default_company_payer, "Club NEW")
        self.assertEqual(
            list(RequestPaymentPurposeConfig.objects.filter(payment_type_config=cash_form).values_list("name", flat=True)),
            ["Ремонтные работы"],
        )
        self.assertTrue(RequestFormPaymentTypeRequester.objects.filter(payment_type_config=cash_form, user=self.requester).exists())

        steps = {s.step: s for s in RequestApprovalStepConfig.objects.filter(payment_type_config__config__tenant=target)}
        self.assertEqual(set(steps), {1, 2})
        self.assertTrue(all(s.is_enabled for s in steps.values()))
        self.assertEqual(list(steps[1].approvers.values_list("approver_user_id", flat=True)), [self.approver.pk])
        self.assertEqual(steps[2].payment_webapp_url, "https://t.me/new_bot/payment")
        self.assertEqual(steps[2].telegram_chat.tenant_id, target.pk)
        self.assertEqual(steps[2].telegram_chat.chat_id, "-100")
        self.assertFalse(TenantTelegramChat.objects.filter(tenant=target, chat_id="-200").exists())

        link = RequestApprovalPurposeExceptionPurpose.objects.get(payment_type_config__config__tenant=target)
        self.assertEqual(link.exception_config.name, "Ремонт")
        self.assertEqual(link.payment_purpose.payment_type_config_id, cash_form.pk)
        self.assertTrue(RequestApprovalPurposeExceptionStepConfig.objects.filter(exception_config=link.exception_config, step=1).exists())

        inv_step = InvestmentApprovalConfigStep.objects.get(config__tenant=target)
        self.assertIsNone(inv_step.telegram_chat)
        self.assertTrue(InvestmentFormConfig.objects.filter(tenant=target, uses_companies=False).exists())
        self.assertEqual(InvestNotificationConfig.objects.get(tenant=target).responsible_user_id, self.admin.pk)
        self.assertEqual(TenantReportSettings.objects.get(tenant=target).pnl_source, "backend")

        cw = CashWithdrawalConfig.objects.get(tenant=target)
        self.assertFalse(cw.is_active)
        self.assertIsNone(cw.card_telegram_chat)
        self.assertTrue(CashWithdrawalConfirmer.objects.filter(config=cw, user=self.admin).exists())
        self.assertTrue(any("Касса Havo" in w for w in report.warnings))

    def test_without_members_steps_are_created_disabled(self):
        report = self._clone(with_members=False)
        target = Tenant.objects.get(subdomain="clone-new")

        steps = RequestApprovalStepConfig.objects.filter(payment_type_config__config__tenant=target)
        self.assertEqual(steps.count(), 2)
        self.assertFalse(any(s.is_enabled for s in steps))
        self.assertFalse(RequestApprovalStepApproverConfig.objects.filter(step_config__in=steps).exists())
        self.assertFalse(InvestNotificationConfig.objects.filter(tenant=target).exists())
        self.assertTrue(any("выключенным" in w for w in report.warnings))

    def test_rerun_adds_nothing_and_fills_bot_link_once_bot_is_set(self):
        self._clone()
        target = Tenant.objects.get(subdomain="clone-new")
        payment_step = RequestApprovalStepConfig.objects.get(payment_type_config__config__tenant=target, step=2)
        self.assertEqual(payment_step.payment_webapp_url, "")

        self.assertEqual(self._clone().changes, [])

        target.telegram_bot_username = "@new_bot"
        target.save(update_fields=["telegram_bot_username"])
        report = self._clone()

        payment_step.refresh_from_db()
        self.assertEqual(payment_step.payment_webapp_url, "https://t.me/new_bot/payment")
        self.assertEqual(len(report.changes), 1)

    def test_existing_target_settings_are_not_overwritten(self):
        target = Tenant.objects.create(name="Club NEW", subdomain="clone-new", is_active=True)
        TenantModuleConfig.objects.create(tenant=target, module_key="cash", is_enabled=False)
        own_form = RequestFormPaymentTypeConfig.objects.create(
            config=RequestFormConfig.objects.create(tenant=target), payment_type=CASH, is_enabled=False,
        )
        RequestPaymentPurposeConfig.objects.create(payment_type_config=own_form, name="Своё", category="Прочие расходы")

        self._clone()

        own_form.refresh_from_db()
        self.assertFalse(own_form.is_enabled)
        self.assertEqual(
            set(RequestPaymentPurposeConfig.objects.filter(payment_type_config=own_form).values_list("name", flat=True)),
            {"Своё", "Ремонтные работы"},
        )
        # Modules are the one thing switched on: a new branch needs the source's modules.
        self.assertTrue(TenantModuleConfig.objects.get(tenant=target, module_key="cash").is_enabled)

    def test_command_dry_run_prints_report(self):
        out = StringIO()
        call_command(
            "clone_tenant_config", "--source=clone-src", "--target=clone-new", "--name=Club NEW", "--with-members", stdout=out,
        )

        self.assertIn("Модуль requests включён", out.getvalue())
        self.assertIn("Dry run complete", out.getvalue())
        self.assertFalse(Tenant.objects.filter(subdomain="clone-new").exists())
