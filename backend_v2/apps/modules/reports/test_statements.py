"""
Fixture totals (today 2026-09-23, start 2025-01, opening 5000):
YTD 2026 revenue 3500 (bank 3200: Jul 1000, Aug 1500, Sep 700; cash Aug 300); same dates 2025: 800.
YTD opex 500 (Маркетинг 300, Аренда 200); 2025: 150. Other 50 (Налоги, Aug). Investor payouts 120 (Aug).
EBIT 3000, net 2950, retained 2830; retained 2025 = 650 → cumulative 8480.
"""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, override_settings

from apps.modules.reports.layouts import ProfessionalCashflowLayout, ProfessionalPnlLayout, label_hash
from apps.modules.reports.ledger import build_ledger
from apps.modules.reports.periods import PeriodSpec, build_column_set
from apps.modules.reports.test_fixtures import OPENING, START_MONTH, TODAY, sample_entries
from apps.modules.reports.statements import build_line_index, build_statement, filter_entries, statement_to_dict


def build(layout, spec, *, entries=None, start_month=START_MONTH):
    column_set = build_column_set(spec, today=TODAY, start_month=start_month)
    return build_statement(entries=sample_entries() if entries is None else entries, layout=layout,
                           column_set=column_set, opening_balance=OPENING, start_month=start_month)


def rows_by_id(statement):
    return {row.id: row for row in statement.rows}


@override_settings(TIME_ZONE="Asia/Tashkent")
class PnlStatementTests(SimpleTestCase):
    def test_ytd_totals_results_and_margin(self):
        rows = rows_by_id(build(ProfessionalPnlLayout(), PeriodSpec(kind="ytd", compare="yoy")))
        self.assertEqual(rows["rev"].values["total"], Decimal("3500"))
        self.assertEqual(rows["rev"].values["compare"], Decimal("800"))
        self.assertEqual(rows["opex"].values["total"], Decimal("500"))
        self.assertEqual(rows["ebit"].values["total"], Decimal("3000"))
        self.assertEqual(rows["net"].values["total"], Decimal("2950"))
        self.assertEqual(rows["retained"].values["total"], Decimal("2830"))
        self.assertEqual(rows["ebit_margin"].values["total"], Decimal("0.8571"))
        self.assertEqual(rows["retained_cum"].values["total"], Decimal("8480"))
        self.assertEqual(rows["retained_cum"].values["compare"], Decimal("5650"))
        self.assertEqual(rows["rev"].values["2026-09"], Decimal("700"))

    def test_rows_are_grouped_and_ordered(self):
        statement = build(ProfessionalPnlLayout(), PeriodSpec(kind="ytd"))
        ids = [row.id for row in statement.rows]
        cash_line = f"rev.cash.{label_hash('Продажа')}"
        self.assertEqual(ids[:4], ["rev", "rev.bank", "rev.cash", cash_line])
        opex_children = [row.id for row in statement.rows if row.parent == "opex"]
        self.assertEqual(opex_children, [f"opex.{label_hash('Маркетинг')}", f"opex.{label_hash('Аренда')}"])
        rows = rows_by_id(statement)
        self.assertEqual((rows["rev"].kind, rows["rev.bank"].kind, rows["rev.cash"].kind), ("group", "line", "group"))
        self.assertEqual((rows["rev.cash"].depth, rows[cash_line].depth), (1, 2))
        self.assertTrue(rows["inv"].separator_before)
        self.assertFalse(rows["ebit"].drillable)

    def test_deltas_are_percent_for_money_and_points_for_margins(self):
        rows = rows_by_id(build(ProfessionalPnlLayout(), PeriodSpec(kind="ytd", compare="yoy")))
        self.assertEqual(rows["rev"].deltas["delta"], {"pct": Decimal("3.3750")})
        self.assertEqual(rows["ebit_margin"].deltas["delta"], {"pp": Decimal("4.5")})

    def test_month_pack(self):
        rows = rows_by_id(build(ProfessionalPnlLayout(), PeriodSpec(kind="month", month="2026-08")))
        rev = rows["rev"]
        self.assertEqual((rev.values["2026-08"], rev.values["2026-07"], rev.values["2025-08"], rev.values["ytd"]),
                         (Decimal("1800"), Decimal("1000"), Decimal("800"), Decimal("2800")))
        self.assertEqual(rev.deltas["delta_prev"], {"pct": Decimal("0.8000")})
        self.assertEqual(rev.deltas["delta_yoy"], {"pct": Decimal("1.2500")})

    def test_kpis_and_chart(self):
        statement = build(ProfessionalPnlLayout(), PeriodSpec(kind="ytd"))
        kpis = {kpi.id: kpi for kpi in statement.kpis}
        self.assertEqual(kpis["rev"].value, Decimal("3500"))
        self.assertEqual(kpis["rev"].comparisons[0].value, Decimal("800"))
        self.assertEqual(kpis["rev"].comparisons[0].delta_pct, Decimal("3.3750"))
        self.assertEqual(kpis["ebit"].ratio, Decimal("0.8571"))
        self.assertEqual(len(kpis["rev"].spark), 12)
        self.assertEqual(kpis["rev"].spark[-1], Decimal("1800"))
        chart = statement.chart
        self.assertEqual(chart["labels"][-1], "Сен*")
        august = chart["labels"].index("Авг")
        self.assertEqual((chart["inflow"][august], chart["outflow"][august], chart["net"][august]),
                         (Decimal("1800"), Decimal("350"), Decimal("1450")))

    def test_margins_are_null_without_revenue(self):
        entries = [entry for entry in sample_entries() if entry.section != "revenue"]
        statement = build(ProfessionalPnlLayout(), PeriodSpec(kind="ytd"), entries=entries)
        rows = rows_by_id(statement)
        self.assertTrue(all(value is None for value in rows["ebit_margin"].values.values()))
        self.assertIsNone({kpi.id: kpi for kpi in statement.kpis}["ebit"].ratio)

    def test_before_start_columns_are_null_and_deltas_suppressed(self):
        statement = build(ProfessionalPnlLayout(), PeriodSpec(kind="ytd", compare="yoy"), start_month="2026-03")
        rows = rows_by_id(statement)
        self.assertIsNone(rows["rev"].values["2026-01"])
        self.assertIsNone(rows["rev"].values["compare"])
        self.assertIsNone(rows["rev"].deltas["delta"])
        self.assertIsNone({kpi.id: kpi for kpi in statement.kpis}["rev"].comparisons[0].value)

    def test_same_category_in_two_sections_stays_apart(self):
        extra = build_ledger({"operational_expenses": [
            {"id": "90", "date": "2026-08-03", "amount": "10", "category": "Налоги", "source": "request"},
        ]})
        entries = sample_entries() + extra
        layout = ProfessionalPnlLayout()
        rows = rows_by_id(build(layout, PeriodSpec(kind="ytd"), entries=entries))
        opex_taxes, other_taxes = f"opex.{label_hash('Налоги')}", f"other.{label_hash('Налоги')}"
        self.assertEqual((rows[opex_taxes].values["total"], rows[other_taxes].values["total"]),
                         (Decimal("10"), Decimal("50")))
        index = build_line_index(entries, layout)
        listed = filter_entries(entries, index, opex_taxes, date(2026, 1, 1), TODAY)
        self.assertEqual([entry.amount for entry in listed], [Decimal("10")])


@override_settings(TIME_ZONE="Asia/Tashkent")
class CashflowStatementTests(SimpleTestCase):
    def test_balances_chain_between_columns(self):
        statement = build(ProfessionalCashflowLayout(), PeriodSpec(kind="ytd"))
        rows = rows_by_id(statement)
        self.assertEqual(rows["open"].values["total"], Decimal("5650"))
        self.assertEqual(rows["close"].values["total"], Decimal("8480"))
        self.assertEqual(rows["flow"].values["total"], Decimal("2830"))
        self.assertEqual((rows["open"].values["2026-08"], rows["close"].values["2026-08"]),
                         (Decimal("6550"), Decimal("7880")))
        months = [column.key for column in statement.columns if column.kind == "period"]
        for current, following in zip(months, months[1:]):
            self.assertEqual(rows["close"].values[current], rows["open"].values[following])


@override_settings(TIME_ZONE="Asia/Tashkent")
class DrillDownInvariantTests(SimpleTestCase):
    def test_every_drillable_cell_equals_its_drilldown(self):
        specs = (
            PeriodSpec(kind="ytd", compare="yoy"),
            PeriodSpec(kind="month", month="2026-08"),
            PeriodSpec(kind="month", month="2026-09"),
            PeriodSpec(kind="year", year=2025, granularity="quarter"),
        )
        for layout in (ProfessionalPnlLayout(), ProfessionalCashflowLayout()):
            for spec in specs:
                entries = sample_entries()
                statement = build(layout, spec, entries=entries)
                index = build_line_index(entries, layout)
                for row in statement.rows:
                    if not row.drillable:
                        continue
                    for column in statement.columns:
                        if column.kind == "delta" or column.before_start:
                            continue
                        listed = sum(
                            (e.amount for e in filter_entries(entries, index, row.id, column.date_from, column.date_to)),
                            start=Decimal("0"),
                        )
                        with self.subTest(report=layout.report, period=spec.kind, row=row.id, column=column.key):
                            self.assertEqual(listed, row.values[column.key])


@override_settings(TIME_ZONE="Asia/Tashkent")
class SerializationTests(SimpleTestCase):
    def test_statement_to_dict_uses_strings(self):
        data = statement_to_dict(build(ProfessionalPnlLayout(), PeriodSpec(kind="ytd", compare="yoy")))
        rev = next(row for row in data["rows"] if row["id"] == "rev")
        margin = next(row for row in data["rows"] if row["id"] == "ebit_margin")
        self.assertEqual(rev["values"]["total"], "3500.00")
        self.assertEqual(rev["deltas"]["delta"], {"pct": "3.3750"})
        self.assertEqual(margin["values"]["total"], "0.8571")
        total = next(column for column in data["columns"] if column["key"] == "total")
        self.assertEqual((total["from"], total["to"], total["kind"]), ("2026-01-01", "2026-09-23", "total"))
        self.assertEqual(data["kpis"][0]["value"], "3500.00")
        self.assertEqual(data["chart"]["inflow"][-1], "700.00")


@override_settings(TIME_ZONE="Asia/Tashkent")
class FilterEveryLineTests(SimpleTestCase):
    def test_filter_without_a_line_takes_every_section(self):
        entries = sample_entries()
        index = build_line_index(entries, ProfessionalPnlLayout())
        picked = filter_entries(entries, index, None, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual((len(picked), sum(entry.amount for entry in picked)), (6, Decimal("2270")))
