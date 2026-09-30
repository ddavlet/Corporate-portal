from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.modules.cash_withdrawals import formatter
from apps.modules.cash_withdrawals.fixtures import CashWithdrawalFixtures
from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt


@override_settings(BASE_DOMAIN="example.com")
class FormatterTests(CashWithdrawalFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_format_money(self):
        self.assertEqual(formatter.format_money(Decimal("100000000.00")), "100 000 000")
        self.assertEqual(formatter.format_money(Decimal("1500.50")), "1 500.50")
        self.assertEqual(formatter.format_money("7807250"), "7 807 250")

    def test_wallet_label_strips_kassa_suffix(self):
        self.assertEqual(formatter.wallet_label(self.wallet), "Основная касса")

    def test_short_user_name(self):
        self.assertEqual(formatter.short_user_name(self.cashier), "Иван П.")
        self.cashier.full_name = ""
        self.assertEqual(formatter.short_user_name(self.cashier), "cw-cashier")

    def test_format_payed_date(self):
        self.assertEqual(formatter.format_payed_date(self.make_request()), "25.09.2026")
        self.assertEqual(formatter.format_payed_date(self.make_request(payed_at=None)), "—")

    def test_pending_card_text_matches_agreed_layout(self):
        receipt = self.make_receipt()
        text = formatter.build_card_text(receipt=receipt, confirmers=[self.cashier, self.accountant])
        self.assertTrue(text.startswith("💸 <b>Ожидается поступление в кассу</b>"))
        self.assertIn("Сумма: <b>100 000 000 UZS</b>", text)
        self.assertIn("Касса: Основная касса", text)
        self.assertIn(f'<a href="https://lemonaqua.example.com/app/requests/{receipt.request_id}">Заявка №{receipt.request_id}</a> · Снятие наличных с банка', text)
        self.assertIn("Комментарий: Снятие денег с банка на расходы", text)
        self.assertIn("Подтвердить могут: Иван П., Мария С.", text)
        self.assertNotIn("Получатель", text)

    def test_card_text_omits_empty_comment_and_escapes_html(self):
        receipt = self.make_receipt(self.make_request(description="", payment_purpose="<b>x</b>"))
        text = formatter.build_card_text(receipt=receipt, confirmers=[])
        self.assertNotIn("Комментарий", text)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", text)

    def test_confirmed_card_text(self):
        receipt = self.make_receipt()
        receipt.status = CashWithdrawalReceipt.Status.CONFIRMED
        receipt.confirmed_by = self.cashier
        receipt.confirmed_at = timezone.make_aware(timezone.datetime(2026, 9, 25, 14, 2))
        text = formatter.build_card_text(receipt=receipt, confirmers=[self.cashier])
        self.assertTrue(text.startswith("✅ <b>Поступило в кассу</b>"))
        self.assertIn("100 000 000 UZS → Основная касса", text)
        self.assertIn("Подтвердил: Иван П. · 25.09.2026 14:02", text)

    def test_closed_card_text(self):
        receipt = self.make_receipt(status=CashWithdrawalReceipt.Status.CLOSED, closed_comment="ошибочное снятие")
        text = formatter.build_card_text(receipt=receipt, confirmers=[])
        self.assertTrue(text.startswith("⛔ <b>Закрыто без дохода</b>"))
        self.assertIn("Причина: ошибочное снятие", text)

    def test_alert_text(self):
        receipt = self.make_receipt()
        text = formatter.build_alert_text(receipt=receipt, days=3, responsible=[self.cashier, self.accountant])
        self.assertTrue(text.startswith("⚠️ <b>Деньги не оприходованы в кассу — 3 дн.</b>"))
        self.assertIn("оплачена 25.09.2026", text)
        self.assertIn("Ответственные: Иван П., Мария С.", text)

    def test_currency_mismatch_text(self):
        req = self.make_request(currency="USD")
        text = formatter.build_currency_mismatch_text(request_obj=req, wallet=self.wallet)
        self.assertIn("валюта USD не совпадает с кассой «Основная касса» (UZS)", text)

    def test_card_buttons(self):
        receipt = self.make_receipt()
        self.assertEqual(
            formatter.card_buttons(receipt),
            [[{"label": "✅ Деньги получены", "value": f"cwr:{receipt.pk}"}]],
        )
