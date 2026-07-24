"""
Tests for the `link_lemon_auto_request_purpose_exceptions` one-time management command.

Covers:
  1. dry-run makes no changes
  2. --apply links a matched payment purpose to the tenant's already-created
     exception config, resolving payment type from the purpose's own config
  3. re-running --apply is idempotent (no duplicate link, no crash)
  4. a purpose name that is ambiguous (exists under two payment types) is skipped
  5. a purpose whose payment type has no pre-created exception config is skipped
  6. tenants outside the --tenant-prefix are left untouched
"""

from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from apps.modules.requests.models import (
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant


def _run(**options):
    out = StringIO()
    call_command("link_lemon_auto_request_purpose_exceptions", stdout=out, **options)
    return out.getvalue()


class LinkLemonAutoRequestPurposeExceptionsTests(TestCase):
    def setUp(self):
        self.lemonfit = Tenant.objects.create(name="Lemonfit", subdomain="lemonfit", is_active=True)
        self.acme = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

        for tenant in (self.lemonfit, self.acme):
            RequestFormConfig.objects.create(tenant=tenant)
            RequestApprovalConfig.objects.create(tenant=tenant)

        # lemonfit: "Нал Зарплата" under Наличные, with an already-created exception config.
        form_cfg = RequestFormConfig.objects.get(tenant=self.lemonfit)
        form_pt_cash = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Наличные", is_enabled=True
        )
        self.salary_purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=form_pt_cash, name="Нал Зарплата"
        )

        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.lemonfit)
        self.appr_pt_cash = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        self.exception_cfg = RequestApprovalPurposeExceptionConfig.objects.create(
            payment_type_config=self.appr_pt_cash, name="Авто заявки нал"
        )

    def test_dry_run_makes_no_changes(self):
        _run()
        self.assertEqual(RequestApprovalPurposeExceptionPurpose.objects.count(), 0)

    def test_apply_links_matched_purpose_to_existing_exception(self):
        _run(apply=True)
        link = RequestApprovalPurposeExceptionPurpose.objects.get()
        self.assertEqual(link.payment_purpose_id, self.salary_purpose.id)
        self.assertEqual(link.exception_config_id, self.exception_cfg.id)
        self.assertEqual(link.payment_type_config_id, self.appr_pt_cash.id)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        _run(apply=True)
        self.assertEqual(RequestApprovalPurposeExceptionPurpose.objects.count(), 1)

    def test_ambiguous_purpose_name_is_skipped(self):
        # Same normalized name ("Таргет") configured under two different payment
        # types for the same tenant -> the command must not guess.
        form_cfg = RequestFormConfig.objects.get(tenant=self.lemonfit)
        form_pt_transfer = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Перечисление", is_enabled=True
        )
        RequestPaymentPurposeConfig.objects.create(payment_type_config=form_pt_transfer, name="Таргет")
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=RequestFormPaymentTypeConfig.objects.get(config=form_cfg, payment_type="Наличные"),
            name="Таргет",
        )

        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.lemonfit)
        appr_pt_transfer = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Перечисление", is_enabled=True
        )
        RequestApprovalPurposeExceptionConfig.objects.create(payment_type_config=appr_pt_transfer, name="Авто заявки безнал")

        _run(apply=True)
        self.assertFalse(
            RequestApprovalPurposeExceptionPurpose.objects.filter(payment_purpose__name="Таргет").exists()
        )

    def test_purpose_without_pre_created_exception_config_is_skipped(self):
        form_cfg = RequestFormConfig.objects.get(tenant=self.lemonfit)
        form_pt_payroll = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Начисление ЗП", is_enabled=True
        )
        RequestPaymentPurposeConfig.objects.create(payment_type_config=form_pt_payroll, name="Канцелярия")

        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.lemonfit)
        # Approval payment-type config exists (so it's not "unconfigured"), but no
        # RequestApprovalPurposeExceptionConfig was pre-created under it yet.
        RequestApprovalPaymentTypeConfig.objects.create(config=appr_cfg, payment_type="Начисление ЗП", is_enabled=True)

        _run(apply=True)
        self.assertFalse(
            RequestApprovalPurposeExceptionPurpose.objects.filter(payment_purpose__name="Канцелярия").exists()
        )

    def test_tenants_outside_prefix_are_untouched(self):
        form_cfg = RequestFormConfig.objects.get(tenant=self.acme)
        form_pt_cash = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Наличные", is_enabled=True
        )
        RequestPaymentPurposeConfig.objects.create(payment_type_config=form_pt_cash, name="Нал Зарплата")
        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.acme)
        appr_pt_cash = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        RequestApprovalPurposeExceptionConfig.objects.create(payment_type_config=appr_pt_cash, name="Авто заявки нал")

        _run(apply=True)
        self.assertFalse(
            RequestApprovalPurposeExceptionPurpose.objects.filter(
                payment_type_config__config__tenant=self.acme
            ).exists()
        )
