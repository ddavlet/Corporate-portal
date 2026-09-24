from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, override_settings

from apps.modules.reports.ledger import build_ledger
from apps.modules.reports.services import finalize_report_payload


@override_settings(TIME_ZONE="Asia/Tashkent")
class BuildLedgerTests(SimpleTestCase):
    def test_entries_keep_section_source_amount_and_date(self):
        payload = {
            "revenue": [{"id": "1", "date": "2026-08-05", "amount": "1500.00", "source": "bank",
                         "purpose": "Поступление", "description": "CLICK реестр"}],
            "operational_expenses": [{"id": "10", "date": "2026-08-01", "amount": "200.00", "source": "request",
                                      "request_id": "10", "vendor": "ООО Офис", "category": "Аренда",
                                      "description": "Аренда за август"}],
            "invest_returns": [{"id": "30", "date": "2026-08-01", "amount": "120.00", "source": "invest_return",
                                "purpose": "Дивиденды", "description": "Получатель: инвестор"}],
        }
        bank, rent, payout = build_ledger(payload)
        self.assertEqual((bank.section, bank.source, bank.amount, bank.date), ("revenue", "bank", Decimal("1500.00"), date(2026, 8, 5)))
        self.assertEqual((bank.title, bank.channel), ("CLICK реестр", "CLICK"))
        self.assertEqual((rent.section, rent.category, rent.request_id, rent.counterparty), ("operational", "Аренда", 10, "ООО Офис"))
        self.assertEqual(rent.title, "Аренда за август")
        self.assertEqual((payout.section, payout.title, payout.counterparty), ("invest_returns", "Дивиденды", "Получатель: инвестор"))

    def test_cash_datetime_is_converted_to_tashkent_date(self):
        payload = {"revenue": [{"id": "1", "date": "2026-03-31T20:30:00+00:00", "amount": "10", "source": "cash",
                                "purpose": "Продажа", "description": "Покупатель"}]}
        (entry,) = build_ledger(payload)
        self.assertEqual(entry.date, date(2026, 4, 1))
        self.assertEqual((entry.title, entry.counterparty, entry.channel), ("Продажа", "Покупатель", ""))

    def test_payload_without_source_is_unknown_and_channel_detected(self):
        payload = {"revenue": [{"id": "1", "date": "2026-03-01", "amount": "5", "description": "PAYME реестр"}]}
        (entry,) = build_ledger(payload)
        self.assertEqual((entry.source, entry.channel, entry.category), ("unknown", "PAYME", "Без категории"))

    def test_amortized_lines_get_unique_ids_and_schedule(self):
        items = [
            {"id": "7", "date": date_text, "amount": "100", "source": "request", "request_id": "7",
             "period_index": index, "periods": 2, "category": "Маркетинг"}
            for index, date_text in ((1, "2026-02-01"), (2, "2026-03-01"))
        ]
        entries = build_ledger({"operational_expenses": items})
        self.assertEqual([e.entry_id for e in entries], ["operational:request:7:1", "operational:request:7:2"])
        self.assertEqual([(e.amortization_index, e.amortization_count) for e in entries], [(1, 2), (2, 2)])
        self.assertEqual(entries[0].request_id, 7)

    def test_duplicate_ids_are_disambiguated(self):
        items = [{"id": "5", "date": "2026-03-01", "amount": "1"}, {"id": "5", "date": "2026-03-01", "amount": "2"}]
        entries = build_ledger({"revenue": items})
        self.assertEqual([e.entry_id for e in entries], ["revenue:unknown:5:0", "revenue:unknown:5:0#1"])

    def test_amounts_with_non_breaking_spaces_are_read(self):
        (entry,) = build_ledger({"revenue": [{"id": "1", "date": "2026-03-01", "amount": "1 234,50"}]})
        self.assertEqual(entry.amount, Decimal("1234.50"))

    def test_unreadable_rows_are_logged(self):
        with self.assertLogs("apps.modules.reports.ledger", level="WARNING") as logs:
            build_ledger({"revenue": [{"id": "1", "date": "31.03.2026", "amount": "10"}]})
        self.assertIn("skipped 1 of 1", logs.output[0])

    def test_rows_with_bad_date_or_amount_are_skipped_and_amounts_are_positive(self):
        payload = {"revenue": [
            {"id": "1", "date": "", "amount": "1"},
            {"id": "2", "date": "2026-03-01", "amount": "abc"},
            {"id": "3", "date": "2026-03-01", "amount": "-4"},
        ]}
        entries = build_ledger(payload)
        self.assertEqual([(e.entry_id, e.amount) for e in entries], [("revenue:unknown:3:0", Decimal("4"))])

    def test_legacy_single_expense_list_counts_as_other_expenses(self):
        payload = finalize_report_payload(
            payload_obj={"expense": [{"id": "9", "date": "2026-03-01", "amount": "40", "category": "Налоги"}]},
            endpoint="/n8n/pnl-data",
            source="n8n",
        )
        (entry,) = build_ledger(payload)
        self.assertEqual((entry.section, entry.category, entry.amount), ("other", "Налоги", Decimal("40")))
