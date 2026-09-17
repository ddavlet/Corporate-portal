"""
Smoke tests for the per-expense-type adapter configs used by
expense_reconciliation_core. These are plain data, but wrong field names
here would silently break every query the engine builds — so we assert
the exact attribute names/values the engine and vendors module expect.
"""

from django.test import SimpleTestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.expense_reconciliation_adapters import ALL_ADAPTERS, BANK, CARD, CASH
from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor


class ExpenseTypeAdapterTests(SimpleTestCase):
    def test_bank_adapter(self):
        self.assertEqual(BANK.key, "bank")
        self.assertIs(BANK.model, BankExpense)
        self.assertEqual(BANK.ref_target, Request.EXPENSE_REF_TARGET_BANK)
        self.assertEqual(BANK.payment_types, (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP))
        self.assertEqual(BANK.amount_field, "debit_turnover")
        self.assertEqual(BANK.date_field, "doc_date")
        self.assertFalse(BANK.date_is_datetime)
        self.assertEqual(BANK.vendor_field, "vendor_id")
        self.assertEqual(BANK.vendor_kind, Vendor.KIND_TRANSFER)
        self.assertTrue(BANK.supports_name_fallback)

    def test_cash_adapter(self):
        self.assertEqual(CASH.key, "cash")
        self.assertIs(CASH.model, CashExpense)
        self.assertEqual(CASH.ref_target, Request.EXPENSE_REF_TARGET_CASH)
        self.assertEqual(CASH.payment_types, (Request.PAYMENT_TYPE_CASH,))
        self.assertEqual(CASH.amount_field, "amount")
        self.assertEqual(CASH.date_field, "expense_at")
        self.assertTrue(CASH.date_is_datetime)
        self.assertEqual(CASH.vendor_field, "vendor_id")
        self.assertEqual(CASH.vendor_kind, Vendor.KIND_CASH)
        self.assertTrue(CASH.supports_name_fallback)

    def test_card_adapter_has_no_vendor(self):
        self.assertEqual(CARD.key, "card")
        self.assertIs(CARD.model, CardExpense)
        self.assertEqual(CARD.ref_target, Request.EXPENSE_REF_TARGET_CARD)
        self.assertEqual(CARD.payment_types, (Request.PAYMENT_TYPE_CARD,))
        self.assertEqual(CARD.amount_field, "amount")
        self.assertEqual(CARD.date_field, "expense_at")
        self.assertTrue(CARD.date_is_datetime)
        self.assertIsNone(CARD.vendor_field)
        self.assertIsNone(CARD.vendor_kind)
        self.assertFalse(CARD.supports_name_fallback)

    def test_all_adapters_keyed_by_key(self):
        self.assertEqual(ALL_ADAPTERS, {"bank": BANK, "cash": CASH, "card": CARD})

    def test_payment_types_do_not_overlap_between_adapters(self):
        seen: set[str] = set()
        for adapter in ALL_ADAPTERS.values():
            for pt in adapter.payment_types:
                self.assertNotIn(pt, seen, f"{pt} claimed by more than one adapter")
                seen.add(pt)
