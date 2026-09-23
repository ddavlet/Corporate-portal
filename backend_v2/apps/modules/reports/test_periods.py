from datetime import date

from django.test import SimpleTestCase

from apps.modules.reports.periods import PeriodSpec, build_column_set, range_label, shift_year

TODAY = date(2026, 9, 23)


def keys(column_set):
    return [c.key for c in column_set.columns]


class BuildColumnSetTests(SimpleTestCase):
    def test_ytd_months_with_partial_current_month(self):
        cs = build_column_set(PeriodSpec(kind="ytd"), today=TODAY, start_month="2024-01")
        self.assertEqual(keys(cs), [f"2026-{m:02d}" for m in range(1, 10)] + ["total"])
        september = cs.columns[8]
        self.assertEqual((september.label, september.sublabel, september.partial), ("Сен*", "1–23", True))
        self.assertEqual(september.date_to, TODAY)
        self.assertEqual(cs.columns[0].label, "Янв")
        self.assertEqual(cs.main.key, "total")
        self.assertEqual(cs.main.sublabel, "янв – 23 сен 2026")
        self.assertEqual([c.key for c in cs.chart_columns], [f"2026-{m:02d}" for m in range(1, 10)])

    def test_ytd_compare_is_like_for_like(self):
        cs = build_column_set(PeriodSpec(kind="ytd", compare="yoy"), today=TODAY, start_month="2024-01")
        self.assertEqual(keys(cs)[-3:], ["total", "compare", "delta"])
        compare = cs.columns[-2]
        self.assertEqual((compare.date_from, compare.date_to), (date(2025, 1, 1), date(2025, 9, 23)))
        self.assertEqual(compare.sublabel, "янв – 23 сен 2025")
        self.assertEqual(cs.columns[-1].delta_of, ("total", "compare"))
        (yoy,) = cs.comparisons
        self.assertEqual((yoy.key, yoy.label, yoy.date_to, yoy.unavailable), ("yoy", "к янв – 23 сен 2025", date(2025, 9, 23), False))

    def test_closed_year_has_twelve_full_months(self):
        cs = build_column_set(PeriodSpec(kind="year", year=2025), today=TODAY, start_month="2024-01")
        periods = [c for c in cs.columns if c.kind == "period"]
        self.assertEqual(len(periods), 12)
        self.assertFalse(any(c.partial for c in periods))
        self.assertEqual(cs.main.sublabel, "2025")

    def test_last_twelve_closed_months(self):
        cs = build_column_set(PeriodSpec(kind="ltm"), today=TODAY, start_month="2024-01")
        periods = [c for c in cs.columns if c.kind == "period"]
        self.assertEqual((periods[0].key, periods[-1].key), ("2025-09", "2026-08"))
        self.assertEqual(periods[0].sublabel, "2025")
        self.assertEqual(cs.main.sublabel, "сен 2025 – авг 2026")

    def test_quarters_group_months(self):
        cs = build_column_set(PeriodSpec(kind="ytd", granularity="quarter"), today=TODAY, start_month="2024-01")
        self.assertEqual(keys(cs), ["2026-Q1", "2026-Q2", "2026-Q3", "total"])
        q3 = cs.columns[2]
        self.assertEqual((q3.label, q3.sublabel, q3.partial), ("III кв.", "июл–сен*", True))

    def test_month_pack_columns(self):
        cs = build_column_set(PeriodSpec(kind="month", month="2026-08"), today=TODAY, start_month="2024-01")
        self.assertEqual(keys(cs), ["2026-08", "2026-07", "delta_prev", "2025-08", "delta_yoy", "ytd"])
        self.assertEqual([c.label for c in cs.columns][:2], ["Август 2026", "Июль 2026"])
        self.assertEqual(cs.main.key, "2026-08")
        self.assertEqual(cs.sort_column.key, "ytd")
        self.assertEqual(cs.columns[-1].date_to, date(2026, 8, 31))
        self.assertEqual([c.label for c in cs.comparisons], ["к июл 2026", "к авг 2025"])
        self.assertEqual(len(cs.chart_columns), 12)
        self.assertEqual(cs.chart_columns[-1].key, "2026-08")

    def test_month_pack_for_current_month_compares_same_dates(self):
        cs = build_column_set(PeriodSpec(kind="month", month="2026-09"), today=TODAY, start_month="2024-01")
        main, year_ago = cs.columns[0], cs.columns[3]
        self.assertEqual((main.date_to, main.sublabel), (TODAY, "1–23 · отчётный"))
        self.assertEqual((year_ago.date_to, year_ago.sublabel), (date(2025, 9, 23), "1–23 · год назад"))
        self.assertEqual(cs.comparisons[1].date_to, date(2025, 9, 23))

    def test_month_pack_for_current_month_cuts_previous_month_to_same_day(self):
        cs = build_column_set(PeriodSpec(kind="month", month="2026-09"), today=TODAY, start_month="2024-01")
        prev = cs.columns[1]
        self.assertEqual((prev.date_to, prev.partial, prev.sublabel), (date(2026, 8, 23), True, "1–23 · предыдущий месяц"))
        self.assertEqual((cs.comparisons[0].date_to, cs.comparisons[0].label), (date(2026, 8, 23), "к 1–23 авг 2026"))

    def test_previous_month_cut_is_clamped_to_its_length(self):
        cs = build_column_set(PeriodSpec(kind="month", month="2026-03"), today=date(2026, 3, 30), start_month="2024-01")
        prev = cs.columns[1]
        self.assertEqual((prev.date_to, prev.partial, prev.sublabel), (date(2026, 2, 28), False, "предыдущий месяц"))

    def test_closed_periods_compare_with_the_whole_leap_february(self):
        pack = build_column_set(PeriodSpec(kind="month", month="2025-02"), today=date(2025, 3, 10), start_month="2024-01")
        self.assertEqual(pack.columns[3].date_to, date(2024, 2, 29))
        ltm = build_column_set(PeriodSpec(kind="ltm", compare="yoy"), today=date(2025, 3, 10), start_month="2023-01")
        compare = next(c for c in ltm.columns if c.key == "compare")
        self.assertEqual(compare.date_to, date(2024, 2, 29))

    def test_columns_before_start_are_flagged(self):
        cs = build_column_set(PeriodSpec(kind="ytd", compare="yoy"), today=TODAY, start_month="2026-03")
        by_key = {c.key: c for c in cs.columns}
        self.assertTrue(by_key["2026-01"].before_start)
        self.assertFalse(by_key["2026-03"].before_start)
        self.assertTrue(by_key["total"].starts_before_data)
        self.assertTrue(by_key["compare"].before_start)
        self.assertTrue(cs.comparisons[0].unavailable)

    def test_spark_months_are_closed_months_since_start(self):
        cs = build_column_set(PeriodSpec(kind="ytd"), today=TODAY, start_month="2024-01")
        self.assertEqual(cs.spark_months[0], "2025-09")
        self.assertEqual(cs.spark_months[-1], "2026-08")
        self.assertEqual(len(cs.spark_months), 12)
        late = build_column_set(PeriodSpec(kind="ytd"), today=TODAY, start_month="2026-03")
        self.assertEqual(late.spark_months, ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"))


class HelpersTests(SimpleTestCase):
    def test_range_label(self):
        self.assertEqual(range_label(date(2025, 1, 1), date(2025, 12, 31)), "2025")
        self.assertEqual(range_label(date(2026, 8, 1), date(2026, 8, 31)), "авг 2026")
        self.assertEqual(range_label(date(2026, 9, 1), date(2026, 9, 23)), "1–23 сен 2026")
        self.assertEqual(range_label(date(2025, 9, 1), date(2026, 8, 31)), "сен 2025 – авг 2026")

    def test_shift_year_clamps_leap_day(self):
        self.assertEqual(shift_year(date(2028, 2, 29), -1), date(2027, 2, 28))
