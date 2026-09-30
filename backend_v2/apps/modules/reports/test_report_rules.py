from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.modules.reports.report_rules import (
    ReportSettingsInvalid,
    parse_opening_balance,
    parse_start_month,
    purpose_bucket,
    rules_snapshot,
    validate_rules,
)
from apps.modules.reports.tests import full_backend_pnl_config


class ReportRulesTests(SimpleTestCase):
    """Rules shared by every report: one validator and one snapshot, whichever report stores them."""

    def test_full_rules_are_valid_and_bank_exclusions_are_optional(self):
        validate_rules(full_backend_pnl_config())
        validate_rules(full_backend_pnl_config(bank_exclude_purposes=["уставного"]))

    def test_names_the_missing_keys(self):
        with self.assertRaises(ReportSettingsInvalid) as ctx:
            validate_rules({})
        self.assertTrue(str(ctx.exception).startswith("rules missing keys:"), str(ctx.exception))

    def test_parses_start_month_and_opening_balance(self):
        self.assertEqual(parse_start_month("2026-02"), date(2026, 2, 1))
        self.assertEqual(parse_opening_balance("1 250 000,50"), Decimal("1250000.50"))
        self.assertEqual(parse_opening_balance(None), Decimal("0"))
        with self.assertRaises(ReportSettingsInvalid):
            parse_start_month("02.2026")

    def test_snapshot_lists_the_rules_and_defaults_the_opening_balance(self):
        snapshot = rules_snapshot(full_backend_pnl_config())
        self.assertEqual(snapshot["start_month"], "2026-02")
        self.assertEqual(snapshot["opening_balance"], "0")
        self.assertEqual(snapshot["bank_exclude_purposes"], [])

    def test_purpose_bucket(self):
        buckets = {"op": {"Аренда"}, "ot": {"Налоги"}, "inv": {"Дивиденды"}}
        self.assertEqual(purpose_bucket(" Аренда ", **buckets), "operational")
        self.assertEqual(purpose_bucket("Налоги", **buckets), "other")
        self.assertEqual(purpose_bucket("Дивиденды", **buckets), "invest_returns")
        self.assertIsNone(purpose_bucket("Прочее", **buckets))
