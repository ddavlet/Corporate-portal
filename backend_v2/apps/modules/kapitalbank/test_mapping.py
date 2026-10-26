from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from .client import StatementDoc
from .mapping import (
    bank_expense_item,
    bank_revenue_item,
    card_expense_item,
    card_revenue_item,
    is_incoming,
    vendor_items,
)

ACC1 = "20208000900000013001"
ACC4 = "20208000900000013004"
CARD = "22618000100000013005"


def make_doc(**kw) -> StatementDoc:
    base = dict(
        general_id="G-1",
        b2_id="B-1",
        num="94430077",
        ddate=date(2026, 2, 24),
        vdate=date(2026, 2, 25),
        acc_dt=ACC4,
        acc_ct=ACC1,
        name_dt="OOO Sender",
        name_ct="OOO Receiver",
        inn_dt="111111111",
        inn_ct="222222222",
        mfo_dt="00444",
        mfo_ct="00555",
        purpose="Переброска остатков",
        dtype="1",
        amount=Decimal("361569643.41"),
        state=1,
        dir=1,
    )
    base.update(kw)
    return StatementDoc(**base)


class MappingTests(SimpleTestCase):
    def test_own_transfer_is_expense_on_sender_and_revenue_on_receiver(self):
        doc = make_doc()
        self.assertIs(is_incoming(doc, ACC1), True)
        self.assertIs(is_incoming(doc, ACC4), False)
        rev = bank_revenue_item(doc)
        self.assertEqual(rev["kredit_turnover"], "361569643.41")
        self.assertEqual(rev["account_no"], ACC4)
        self.assertEqual(rev["doc_no"], "94430077")
        exp = bank_expense_item(doc)
        self.assertEqual(exp["debit_turnover"], "361569643.41")
        self.assertEqual(exp["account_no"], ACC1)

    def test_bank_item_fields_match_n8n(self):
        doc = make_doc()
        self.assertEqual(
            bank_revenue_item(doc),
            {
                "doc_date": "2026-02-24",
                "process_date": "2026-02-25",
                "account_name": "OOO Sender",
                "inn": "111111111",
                "account_no": ACC4,
                "mfo": "00444",
                "kredit_turnover": "361569643.41",
                "payment_purpose": "Переброска остатков",
                "doc_no": "94430077",
                "external_id": "G-1",
            },
        )
        self.assertEqual(
            bank_expense_item(doc),
            {
                "doc_date": "2026-02-24",
                "process_date": "2026-02-25",
                "account_name": "OOO Receiver",
                "inn": "222222222",
                "account_no": ACC1,
                "mfo": "00555",
                "debit_turnover": "361569643.41",
                "payment_purpose": "Переброска остатков",
                "doc_no": "94430077",
                "external_id": "G-1",
            },
        )

    def test_amount_always_two_decimals(self):
        self.assertEqual(bank_revenue_item(make_doc(amount=Decimal("5")))["kredit_turnover"], "5.00")
        self.assertEqual(bank_expense_item(make_doc(amount=Decimal("0.1")))["debit_turnover"], "0.10")

    def test_empty_inn_becomes_zero(self):
        doc = make_doc(inn_dt="", inn_ct="")
        self.assertEqual(bank_revenue_item(doc)["inn"], 0)
        self.assertEqual(bank_expense_item(doc)["inn"], 0)
        self.assertEqual(card_revenue_item(doc, wallet_id=1)["payload"]["inn"], 0)
        self.assertEqual(card_expense_item(doc, wallet_id=1)["payload"]["inn"], 0)
        self.assertEqual(vendor_items([bank_expense_item(doc)])[0]["inn"], 0)

    def test_vendor_items_dedup_by_account(self):
        a = bank_expense_item(make_doc(general_id="G-1"))
        b = bank_expense_item(make_doc(general_id="G-2", num="2"))
        c = bank_expense_item(make_doc(general_id="G-3", acc_ct="X2", name_ct="Other"))
        self.assertEqual(
            vendor_items([a, b, c]),
            [
                {"kind": "transfer", "name": "OOO Receiver", "inn": "222222222", "account_no": ACC1},
                {"kind": "transfer", "name": "Other", "inn": "222222222", "account_no": "X2"},
            ],
        )

    def test_card_items_fields_match_n8n(self):
        doc = make_doc(acc_dt=CARD, acc_ct=ACC1, amount=Decimal("1000"))
        rev = card_revenue_item(doc, wallet_id=7)
        self.assertEqual(rev["revenue_at"], "2026-02-24T00:00:00+05:00")
        self.assertEqual(rev["operation"], "Пополение корп-карты")
        self.assertEqual(rev["total_sum"], "1000.00")
        self.assertEqual(rev["currency"], "UZS")
        self.assertEqual(rev["counterparty"], "OOO Sender")
        self.assertEqual(rev["comment"], "Переброска остатков")
        self.assertEqual(rev["external_id"], "G-1")
        self.assertEqual(rev["account"], CARD)
        self.assertEqual(rev["wallet_id"], 7)
        self.assertEqual(
            rev["payload"],
            {
                "doc_no": "94430077",
                "inn": "111111111",
                "mfo": "00444",
                "process_date": "2026-02-25",
                "account_no": CARD,
                "account_name": "OOO Sender",
            },
        )
        exp = card_expense_item(doc, wallet_id=7)
        self.assertEqual(exp["expense_at"], "2026-02-24T00:00:00+05:00")
        self.assertEqual(exp["amount"], "1000.00")
        self.assertEqual(exp["currency"], "UZS")
        self.assertEqual(exp["title"], "OOO Sender")
        self.assertEqual(exp["note"], "Переброска остатков")
        self.assertEqual(exp["external_id"], "G-1")
        self.assertEqual(exp["wallet_id"], 7)
        self.assertEqual(exp["payload"]["inn"], "222222222")
        self.assertEqual(exp["payload"]["mfo"], "00555")
        self.assertEqual(exp["payload"]["account_no"], ACC1)
        self.assertEqual(exp["payload"]["account_name"], "OOO Receiver")
