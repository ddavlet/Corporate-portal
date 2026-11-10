from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.modules.cash_desk.card_topup_formatter import build_card_topup_text


def _request(**overrides):
    data = {
        "pk": 42,
        "payed_at": 20261110,
        "billing_date": date(2026, 11, 9),
        "amount": Decimal("5000000.00"),
        "currency": "UZS",
        "payment_purpose": "Пополнение карты",
        "vendor": "ООО Ромашка",
        "description": "На хозрасходы",
        "category": "Хозяйственные",
        "company_payer": "Neuron Med",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


CARD = {"name": "Humo Neuron", "current_balance": "2500000.00", "currency": "UZS"}


class CardTopupFormatterTests(SimpleTestCase):
    def test_full_text_with_card(self):
        text = build_card_topup_text(request_obj=_request(), card=CARD)
        self.assertEqual(
            text,
            "\n".join(
                [
                    "💰 <b>Движение денежных средств</b>",
                    "",
                    "🆔 <b>ID:</b> 42",
                    "📅 <b>Дата:</b> 10.11.2026",
                    "🔄 <b>Вид движения:</b> Пополнение корпоративной карты",
                    "",
                    "💵 <b>Сумма:</b> <code>5 000 000 UZS</code>",
                    "",
                    "📝 <b>Назначение платежа:</b>",
                    "Пополнение карты",
                    "👤 <b>Получатель:</b> ООО Ромашка",
                    "💬 <b>Комментарий:</b>",
                    "На хозрасходы",
                    "",
                    "💳 <b>Категория:</b> Хозяйственные",
                    "🏢 <b>Плательщик:</b> Neuron Med",
                    "",
                    "💳 <b>Карта:</b> Humo Neuron",
                    "💰 <b>Остаток на карте:</b> <code>2 500 000 UZS</code>",
                ]
            ),
        )

    def test_without_card_omits_card_and_balance(self):
        text = build_card_topup_text(request_obj=_request(), card=None)
        self.assertNotIn("Карта:", text)
        self.assertNotIn("Остаток на карте", text)
        self.assertTrue(text.endswith("🏢 <b>Плательщик:</b> Neuron Med"))

    def test_fractional_balance_and_amount(self):
        card = {"name": "Visa", "current_balance": "-120.50", "currency": "USD"}
        text = build_card_topup_text(request_obj=_request(amount=Decimal("99.90"), currency="USD"), card=card)
        self.assertIn("💵 <b>Сумма:</b> <code>99.90 USD</code>", text)
        self.assertIn("💰 <b>Остаток на карте:</b> <code>-120.50 USD</code>", text)

    def test_falls_back_to_billing_date(self):
        text = build_card_topup_text(request_obj=_request(payed_at=None), card=None)
        self.assertIn("📅 <b>Дата:</b> 09.11.2026", text)

    def test_empty_fields_are_dashes(self):
        req = _request(payment_purpose="", vendor=None, description="  ", category=None, company_payer="")
        text = build_card_topup_text(request_obj=req, card={"name": "", "current_balance": "0", "currency": "UZS"})
        self.assertIn("📝 <b>Назначение платежа:</b>\n—", text)
        self.assertIn("👤 <b>Получатель:</b> —", text)
        self.assertIn("💬 <b>Комментарий:</b>\n—", text)
        self.assertIn("💳 <b>Категория:</b> —", text)
        self.assertIn("🏢 <b>Плательщик:</b> —", text)
        self.assertIn("💳 <b>Карта:</b> —", text)

    def test_html_is_escaped(self):
        req = _request(
            vendor="<b>Хак</b> & Co",
            description="<script>x</script>",
            payment_purpose="A<B",
            category="1 > 0",
            company_payer='"Q"',
            currency="<U>",
        )
        card = {"name": "<i>Card</i>", "current_balance": "1", "currency": "&"}
        text = build_card_topup_text(request_obj=req, card=card)
        self.assertIn("👤 <b>Получатель:</b> &lt;b&gt;Хак&lt;/b&gt; &amp; Co", text)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", text)
        self.assertIn("A&lt;B", text)
        self.assertIn("1 &gt; 0", text)
        self.assertIn("&quot;Q&quot;", text)
        self.assertIn("&lt;U&gt;", text)
        self.assertIn("💳 <b>Карта:</b> &lt;i&gt;Card&lt;/i&gt;", text)
        self.assertIn("<code>1 &amp;</code>", text)
        self.assertNotIn("<script>", text)
