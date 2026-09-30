from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.tests import full_backend_pnl_config
from apps.tenants.models import Tenant

migration = import_module("apps.modules.reports.migrations.0005_cashflow_own_rules")


class CashflowOwnRulesMigrationTests(TestCase):
    """On deploy every Cashflow gets a copy of today's PnL rules, so no number changes."""

    def _row(self, subdomain, **fields):
        tenant = Tenant.objects.create(name=subdomain, subdomain=subdomain)
        return TenantReportSettings.objects.create(tenant=tenant, **fields)

    def test_copies_the_pnl_rules_and_keeps_the_cashflow_opening_balance(self):
        row = self._row(
            "mig1",
            pnl_config=full_backend_pnl_config(opening_balance="111", bank_exclude_purposes=["уставного"]),
            cashflow_config={"opening_balance": "222"},
        )
        migration.copy_pnl_rules_to_cashflow(django_apps, None)
        row.refresh_from_db()
        self.assertEqual(row.cashflow_config, full_backend_pnl_config(opening_balance="222"))
        self.assertEqual(row.pnl_config["bank_exclude_purposes"], ["уставного"])

    def test_a_cashflow_without_opening_balance_stays_at_zero(self):
        row = self._row("mig2", pnl_config=full_backend_pnl_config(opening_balance="999"), cashflow_config={})
        migration.copy_pnl_rules_to_cashflow(django_apps, None)
        row.refresh_from_db()
        self.assertEqual(row.cashflow_config, full_backend_pnl_config())

    def test_leaves_rows_that_need_nothing(self):
        own = self._row(
            "mig3",
            pnl_config=full_backend_pnl_config(),
            cashflow_config=full_backend_pnl_config(start_month="2025-01"),
        )
        empty = self._row("mig4", pnl_config={}, cashflow_config={"opening_balance": "5"})
        migration.copy_pnl_rules_to_cashflow(django_apps, None)
        own.refresh_from_db()
        empty.refresh_from_db()
        self.assertEqual(own.cashflow_config["start_month"], "2025-01")
        self.assertEqual(empty.cashflow_config, {"opening_balance": "5"})

    def test_reverse_keeps_only_the_opening_balance(self):
        row = self._row("mig5", cashflow_config=full_backend_pnl_config(opening_balance="222"))
        migration.keep_only_cashflow_opening_balance(django_apps, None)
        row.refresh_from_db()
        self.assertEqual(row.cashflow_config, {"opening_balance": "222"})
