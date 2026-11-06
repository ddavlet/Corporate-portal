"""Tests for fix_invest_returns: billing month shift, recipient and type fixes on chosen InvestReturn rows."""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.investments.models import InvestReturn
from apps.tenants.models import Tenant

User = get_user_model()

INVESTOR = InvestReturn.Recipient.INVESTOR
PARTNER = InvestReturn.Recipient.PARTNER
PRINCIPAL = InvestReturn.ReturnType.PRINCIPAL
PROFIT_SHARE = InvestReturn.ReturnType.PROFIT_SHARE


class FixInvestReturnsCommandTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="fix-invret-admin", password="x")
        self.tenant = Tenant.objects.create(name="Neuron", subdomain="fix-invret", is_active=True)
        self.other = Tenant.objects.create(name="Other", subdomain="fix-invret-other", is_active=True)
        # Imported rows: billing_date == payout date (month-end), as in the NeuronMed 2024–2025 import.
        self.inv_oct = self._ret(date(2024, 10, 31), date(2024, 10, 31), "2482.87", INVESTOR, PRINCIPAL)
        self.inv_dec = self._ret(date(2024, 12, 31), date(2024, 12, 31), "23386.24", INVESTOR, PRINCIPAL)
        self.partner_dec = self._ret(date(2024, 12, 31), date(2024, 12, 31), "6000.00", PARTNER, PROFIT_SHARE)
        # Correct 2026 row: must stay as is.
        self.inv_2026 = self._ret(date(2025, 12, 31), date(2026, 1, 1), "28935.00", INVESTOR, PRINCIPAL)
        self.foreign = self._ret(
            date(2024, 12, 31), date(2024, 12, 31), "100.00", PARTNER, PROFIT_SHARE, tenant=self.other
        )

    def _ret(self, paid, billing, amount, recipient, kind, *, tenant=None):
        return InvestReturn.objects.create(
            tenant=tenant or self.tenant, date=paid, billing_date=billing, sum=Decimal(amount), currency="USD",
            confirmed=True, type=kind, recipient=recipient, created_by=self.admin,
        )

    def _run(self, **opts) -> str:
        out = StringIO()
        call_command("fix_invest_returns", tenant=str(self.tenant.pk), stdout=out, **opts)
        return out.getvalue()

    def _state(self, row):
        row.refresh_from_db()
        return row.billing_date, row.recipient, row.type, row.sum, row.date

    def test_dry_run_reports_and_changes_nothing(self):
        ids = f"{self.inv_oct.pk}-{self.partner_dec.pk}"
        before = [self._state(r) for r in (self.inv_oct, self.inv_dec, self.partner_dec)]
        out = self._run(ids=ids, billing_month_offset=1)
        self.assertIn("Would change: 3", out)
        self.assertIn("billing_date: 2024-10-31 -> 2024-11-01", out)
        self.assertEqual(before, [self._state(r) for r in (self.inv_oct, self.inv_dec, self.partner_dec)])

    def test_apply_shifts_billing_month_from_payout_date_and_is_idempotent(self):
        ids = f"{self.inv_oct.pk}-{self.partner_dec.pk}"
        self._run(ids=ids, billing_month_offset=1, apply=True)
        self.assertEqual(self._state(self.inv_oct)[0], date(2024, 11, 1))
        self.assertEqual(self._state(self.inv_dec)[0], date(2025, 1, 1))
        self.assertEqual(self._state(self.partner_dec)[0], date(2025, 1, 1))
        # Sums and payout dates untouched; rows outside the ids untouched.
        self.assertEqual(self._state(self.inv_oct)[3:], (Decimal("2482.87"), date(2024, 10, 31)))
        self.assertEqual(self._state(self.inv_2026)[0], date(2026, 1, 1))
        # Second run: offset counts from the payout date, so nothing shifts twice.
        self.assertIn("Would change: 0", self._run(ids=ids, billing_month_offset=1))

    def test_partner_rows_become_investor_principal(self):
        self._run(recipient_from="PARTNER", set_recipient="INVESTOR", set_type="PRINCIPAL", apply=True)
        self.assertEqual(self._state(self.partner_dec)[1:3], (INVESTOR, PRINCIPAL))
        self.assertEqual(self._state(self.partner_dec)[3], Decimal("6000.00"))
        # Other tenant's partner row is not touched.
        self.assertEqual(self._state(self.foreign)[1:3], (PARTNER, PROFIT_SHARE))
        self.assertEqual(InvestReturn.objects.filter(tenant=self.tenant, recipient=PARTNER).count(), 0)

    def test_accepts_choice_values_as_well_as_names(self):
        self._run(recipient_from="партнер", set_recipient="инвестор", set_type="тело_инвестиций", apply=True)
        self.assertEqual(self._state(self.partner_dec)[1:3], (INVESTOR, PRINCIPAL))

    def test_ids_from_another_tenant_are_rejected(self):
        with self.assertRaisesMessage(CommandError, str(self.foreign.pk)):
            self._run(ids=f"{self.inv_oct.pk},{self.foreign.pk}", billing_month_offset=1, apply=True)
        self.assertEqual(self._state(self.inv_oct)[0], date(2024, 10, 31))

    def test_requires_selector_and_change(self):
        with self.assertRaises(CommandError):
            self._run(billing_month_offset=1)
        with self.assertRaises(CommandError):
            self._run(ids=str(self.inv_oct.pk))
        with self.assertRaises(CommandError):
            self._run(recipient_from="PARTNER", set_recipient="nobody")
