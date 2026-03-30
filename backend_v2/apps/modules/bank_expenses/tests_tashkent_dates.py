from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework import serializers

from apps.modules.bank_expenses.serializers import _apply_expense_calendar_from_doc_date
from apps.modules.bank_expenses.tashkent_dates import (
    TASHKENT_TZ,
    TashkentFlexibleDateField,
    coerce_input_to_tashkent_date,
    doc_date_candidates_for_composite_lookup,
)


class CoerceInputToTashkentDateTests(SimpleTestCase):
    def test_date_only_string_unchanged(self):
        self.assertEqual(coerce_input_to_tashkent_date("2026-03-01"), date(2026, 3, 1))

    def test_date_only_stripped(self):
        self.assertEqual(coerce_input_to_tashkent_date("  2026-03-01  "), date(2026, 3, 1))

    def test_utc_z_becomes_next_calendar_day_in_tashkent(self):
        # 2026-03-01 19:00 UTC = 2026-03-02 00:00 +05
        self.assertEqual(
            coerce_input_to_tashkent_date("2026-03-01T19:00:00.000Z"),
            date(2026, 3, 2),
        )

    def test_naive_datetime_is_wall_clock_tashkent(self):
        self.assertEqual(
            coerce_input_to_tashkent_date("2026-03-01T19:00:00"),
            date(2026, 3, 1),
        )

    def test_offset_aware_converts_to_tashkent_date(self):
        self.assertEqual(
            coerce_input_to_tashkent_date("2026-03-01T04:00:00+00:00"),
            date(2026, 3, 1),
        )

    def test_python_date_passthrough(self):
        self.assertEqual(coerce_input_to_tashkent_date(date(2026, 5, 10)), date(2026, 5, 10))

    def test_python_datetime_aware_utc(self):
        dt = datetime(2026, 3, 1, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(coerce_input_to_tashkent_date(dt), date(2026, 3, 2))

    def test_python_datetime_naive_is_tashkent_wall(self):
        dt = datetime(2026, 3, 1, 19, 0, 0)
        self.assertEqual(coerce_input_to_tashkent_date(dt), date(2026, 3, 1))


class ApplyExpenseCalendarFromDocDateTests(SimpleTestCase):
    def test_fills_missing_ymd_from_doc_date(self):
        attrs = {"doc_date": date(2026, 3, 2)}
        _apply_expense_calendar_from_doc_date(attrs, None)
        self.assertEqual(attrs["expense_year"], 2026)
        self.assertEqual(attrs["expense_month"], 3)
        self.assertEqual(attrs["expense_day"], 2)

    def test_preserves_explicit_year(self):
        attrs = {"doc_date": date(2026, 3, 2), "expense_year": 2025}
        _apply_expense_calendar_from_doc_date(attrs, None)
        self.assertEqual(attrs["expense_year"], 2025)
        self.assertEqual(attrs["expense_month"], 3)
        self.assertEqual(attrs["expense_day"], 2)


class DocDateCompositeLookupCandidatesTests(SimpleTestCase):
    def test_iso_z_includes_tashkent_and_legacy_prefix(self):
        c = doc_date_candidates_for_composite_lookup("2026-03-01T19:00:00.000Z")
        self.assertEqual(c[0], date(2026, 3, 2))
        self.assertIn(date(2026, 3, 1), c)

    def test_date_only_single_candidate(self):
        self.assertEqual(
            doc_date_candidates_for_composite_lookup("2026-03-01"),
            [date(2026, 3, 1)],
        )


class TashkentFlexibleDateFieldTests(SimpleTestCase):
    def test_field_accepts_date_only_and_iso_z(self):
        class _S(serializers.Serializer):
            doc_date = TashkentFlexibleDateField()

        s1 = _S(data={"doc_date": "2026-03-01"})
        self.assertTrue(s1.is_valid(), s1.errors)
        self.assertEqual(s1.validated_data["doc_date"], date(2026, 3, 1))

        s2 = _S(data={"doc_date": "2026-03-01T19:00:00.000Z"})
        self.assertTrue(s2.is_valid(), s2.errors)
        self.assertEqual(s2.validated_data["doc_date"], date(2026, 3, 2))

    def test_tashkent_tz_constant(self):
        self.assertEqual(TASHKENT_TZ.key, "Asia/Tashkent")
