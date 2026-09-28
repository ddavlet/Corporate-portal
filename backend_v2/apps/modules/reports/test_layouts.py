import hashlib
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.modules.reports.layouts import (
    ByCategoryGrouping,
    ProfessionalCashflowLayout,
    ProfessionalPnlLayout,
    RevenueBySourceGrouping,
    label_hash,
)
from apps.modules.reports.ledger import LedgerEntry


def entry(source: str, category: str) -> LedgerEntry:
    return LedgerEntry(entry_id="x", section="revenue", source=source, date=date(2026, 8, 1), amount=Decimal("1"),
                       category=category, title="", counterparty="", request_id=None, channel="",
                       amortization_index=None, amortization_count=None)


class GroupingTests(SimpleTestCase):
    def test_label_hash_is_short_sha1(self):
        self.assertEqual(label_hash("Аренда"), hashlib.sha1("Аренда".encode("utf-8")).hexdigest()[:8])

    def test_revenue_by_source(self):
        grouping = RevenueBySourceGrouping()
        self.assertEqual(grouping.path(entry("bank", "Поступление в банк")), (("bank", "Банк"),))
        self.assertEqual(grouping.path(entry("cash", "Продажа")), (("cash", "Касса"), (label_hash("Продажа"), "Продажа")))
        self.assertEqual(grouping.path(entry("unknown", "Выручка n8n")), ((label_hash("Выручка n8n"), "Выручка n8n"),))
        self.assertEqual(grouping.fixed_order, ("bank", "cash"))

    def test_by_category(self):
        self.assertEqual(ByCategoryGrouping().path(entry("request", "Аренда")), ((label_hash("Аренда"), "Аренда"),))


class ProfessionalLayoutTests(SimpleTestCase):
    def test_pnl_row_order(self):
        self.assertEqual(
            ProfessionalPnlLayout().item_ids(),
            ("rev", "opex", "ebit", "ebit_margin", "other", "net", "net_margin", "inv", "retained", "retained_cum"),
        )

    def test_cashflow_row_order(self):
        self.assertEqual(
            ProfessionalCashflowLayout().item_ids(),
            ("open", "in", "out_op", "out_other", "out_inv", "flow", "close"),
        )
