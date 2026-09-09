"""
Tests for the `add_cash_register_transfer_purpose` one-time management command.

Covers:
  1. dry-run makes no changes
  2. --apply creates the purpose (with category) for a tenant that has "Наличные" configured
  3. re-running --apply is idempotent (no duplicate row)
  4. a tenant without RequestFormConfig is skipped, not crashed
  5. a tenant without a "Наличные" payment type config is skipped
  6. --tenant limits the run to a single tenant
  7. an existing purpose with a different category is left untouched (not overwritten)
"""

from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from apps.modules.requests.models import (
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant

PURPOSE_NAME = "Перевод между кассами"


def _run(**options):
    out = StringIO()
    call_command("add_cash_register_transfer_purpose", stdout=out, **options)
    return out.getvalue()


class AddCashRegisterTransferPurposeTests(TestCase):
    def setUp(self):
        self.lemonfit = Tenant.objects.create(name="Lemonfit", subdomain="lemonfit", is_active=True)
        self.acme = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

        form_cfg = RequestFormConfig.objects.create(tenant=self.lemonfit)
        self.pt_cash = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Наличные", is_enabled=True
        )
        # acme: has a RequestFormConfig, but no "Наличные" payment type config.
        RequestFormConfig.objects.create(tenant=self.acme)

    def test_dry_run_makes_no_changes(self):
        _run()
        self.assertEqual(RequestPaymentPurposeConfig.objects.count(), 0)

    def test_apply_creates_purpose_with_category(self):
        _run(apply=True)
        purpose = RequestPaymentPurposeConfig.objects.get(payment_type_config=self.pt_cash, name=PURPOSE_NAME)
        self.assertEqual(purpose.category, PURPOSE_NAME)
        self.assertTrue(purpose.is_active)

    def test_apply_twice_is_idempotent(self):
        _run(apply=True)
        _run(apply=True)
        self.assertEqual(
            RequestPaymentPurposeConfig.objects.filter(payment_type_config=self.pt_cash, name=PURPOSE_NAME).count(),
            1,
        )

    def test_tenant_without_form_config_is_skipped_not_crashed(self):
        Tenant.objects.create(name="NoForm", subdomain="noform", is_active=True)
        _run(apply=True)  # must not raise
        self.assertEqual(RequestPaymentPurposeConfig.objects.count(), 1)

    def test_tenant_without_cash_payment_type_is_skipped(self):
        _run(apply=True)
        self.assertEqual(
            RequestPaymentPurposeConfig.objects.filter(payment_type_config__config__tenant=self.acme).count(),
            0,
        )

    def test_tenant_filter_limits_to_one_tenant(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        other_form_cfg = RequestFormConfig.objects.create(tenant=other)
        other_pt_cash = RequestFormPaymentTypeConfig.objects.create(
            config=other_form_cfg, payment_type="Наличные", is_enabled=True
        )

        _run(apply=True, tenant=self.lemonfit.id)

        self.assertTrue(
            RequestPaymentPurposeConfig.objects.filter(payment_type_config=self.pt_cash, name=PURPOSE_NAME).exists()
        )
        self.assertFalse(
            RequestPaymentPurposeConfig.objects.filter(payment_type_config=other_pt_cash, name=PURPOSE_NAME).exists()
        )

    def test_existing_purpose_with_different_category_is_not_overwritten(self):
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=self.pt_cash, name=PURPOSE_NAME, category="Другая категория"
        )
        _run(apply=True)
        purpose = RequestPaymentPurposeConfig.objects.get(payment_type_config=self.pt_cash, name=PURPOSE_NAME)
        self.assertEqual(purpose.category, "Другая категория")
