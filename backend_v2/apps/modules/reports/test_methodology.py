from datetime import datetime

from django.test import SimpleTestCase

from apps.modules.reports.methodology import build_methodology

SETTINGS = {
    "start_month": "2025-01",
    "opening_balance": "5000",
    "bank_exclude_purposes": ["Возврат займа"],
    "cash_exclude_operations": ["Инкассация"],
    "request_exclude_categories": ["Внутренние переводы"],
    "request_payment_types_for_pnl": ["Перечисление"],
    "payment_purpose_operational": ["Аренда"],
    "payment_purpose_other": ["Налоги"],
    "payment_purpose_invest_returns": [],
    "invest_return_type_operational": [],
    "invest_return_type_other": [],
    "invest_return_type_invest_returns": ["тело_инвестиций"],
}
GENERATED = datetime(2026, 9, 23, 14, 32)


class BuildMethodologyTests(SimpleTestCase):
    def test_pnl_rules(self):
        rules = {
            r["label"]: r["text"]
            for r in build_methodology(report="pnl", report_settings=SETTINGS, source="backend", generated_at=GENERATED)
        }
        self.assertEqual(rules["Период отчёта"], "с января 2025 года")
        self.assertEqual(rules["Начальный остаток"], "5 000,00 сум на 01.01.2025")
        self.assertIn("«Возврат займа»", rules["Выручка: банк"])
        self.assertIn("«Инкассация»", rules["Выручка: касса"])
        self.assertIn("«Перечисление»", rules["Расходы"])
        self.assertIn("«Внутренние переводы»", rules["Расходы"])
        self.assertIn("«Тело инвестиций»", rules["Выплаты инвесторам"])
        self.assertIn("амортизацией", rules["Дата расхода"])
        self.assertEqual(rules["Источник данных"], "данные системы · сформировано 23.09.2026 14:32")

    def test_cashflow_bank_has_no_exclusions(self):
        rules = {
            r["label"]: r["text"]
            for r in build_methodology(report="cashflow", report_settings=SETTINGS, source="backend", generated_at=GENERATED)
        }
        self.assertEqual(rules["Выручка: банк"], "Все поступления на расчётный счёт, без исключений.")
        self.assertEqual(rules["Дата расхода"], "Дата фактической оплаты; амортизация не применяется.")

    def test_n8n_without_settings(self):
        rules = build_methodology(report="pnl", report_settings=None, source="n8n", generated_at=GENERATED)
        self.assertEqual([r["label"] for r in rules], ["Правила", "Источник данных"])
        self.assertEqual(rules[1]["text"], "сценарий n8n · сформировано 23.09.2026 14:32")
