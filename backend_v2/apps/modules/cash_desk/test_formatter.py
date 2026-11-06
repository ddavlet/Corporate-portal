from decimal import Decimal

from django.test import TestCase

from apps.modules.cash_desk.fixtures import CashDeskFixtures
from apps.modules.cash_desk.formatter import build_movement_text
from apps.modules.cash_desk.models import CashDeskMessage
from apps.modules.cash_desk.transfer_revenue import TransferDestination

EXPENSE = CashDeskMessage.Kind.EXPENSE
TRANSFER = CashDeskMessage.Kind.TRANSFER


class MovementTextTests(CashDeskFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _balances(self, *, safe_active=True):
        return [
            {
                "wallet_id": self.main.id,
                "display_name": "Основная касса (касса)",
                "current_balance": Decimal("2500000"),
                "currency": "UZS",
                "anchor_is_active": True,
            },
            {
                "wallet_id": self.safe.id,
                "display_name": "Сейф",
                "current_balance": Decimal("100000.50"),
                "currency": "UZS",
                "anchor_is_active": safe_active,
            },
            {
                "wallet_id": self.usd.id,
                "display_name": "Касса USD",
                "current_balance": Decimal("300"),
                "currency": "USD",
                "anchor_is_active": True,
            },
        ]

    def test_expense_text_exact(self):
        req = self.make_request()
        text = build_movement_text(
            request_obj=req, kind=EXPENSE, from_wallet=self.main, destination=None, balances=self._balances()
        )
        expected = "\n".join(
            [
                "💰 <b>Движение денежных средств</b>",
                "",
                f"🆔 <b>ID:</b> {req.pk}",
                "📅 <b>Дата:</b> 06.11.2026",
                "🔄 <b>Вид движения:</b> Расход",
                "🏦 <b>Касса:</b> Основная касса",
                "",
                "💵 <b>Сумма:</b> <code>1 500 000 UZS</code>",
                "",
                "📝 <b>Назначение платежа:</b>",
                "Хозтовары",
                "👤 <b>Получатель:</b> ООО Ромашка",
                "💬 <b>Комментарий:</b>",
                "Описание",
                "",
                "💳 <b>Категория:</b> Хозяйственные",
                "🏢 <b>Плательщик:</b> Lemonfit AQUA",
                "",
                "📊 <b>Остатки по всем кассам:</b>",
                "👉 <b>Основная касса: 2 500 000 UZS</b>",
                "🏦 Сейф: 100 000.50 UZS",
                "🏦 Касса USD: 300 USD",
            ]
        )
        self.assertEqual(text, expected)

    def test_transfer_marks_both_registers(self):
        req = self.make_request()
        dest = TransferDestination(wallet=self.safe, amount=Decimal("1500000"), currency="UZS")
        text = build_movement_text(
            request_obj=req, kind=TRANSFER, from_wallet=self.main, destination=dest, balances=self._balances()
        )
        self.assertIn("🔄 <b>Вид движения:</b> Перемещение", text)
        self.assertIn("🏦 <b>Касса:</b> Основная касса → Сейф", text)
        self.assertIn("👉 <b>Основная касса: 2 500 000 UZS</b>", text)
        self.assertIn("👉 <b>Сейф: 100 000.50 UZS</b>", text)
        self.assertIn("🏦 Касса USD: 300 USD", text)
        self.assertNotIn("Зачислено", text)

    def test_cross_currency_shows_credited_line(self):
        req = self.make_request()
        dest = TransferDestination(wallet=self.usd, amount=Decimal("120"), currency="USD")
        text = build_movement_text(
            request_obj=req, kind=TRANSFER, from_wallet=self.main, destination=dest, balances=self._balances()
        )
        self.assertIn("💵 <b>Сумма:</b> <code>1 500 000 UZS</code>\n💱 <b>Зачислено:</b> <code>120 USD</code>", text)

    def test_html_escaped(self):
        req = self.make_request(vendor="ООО <Рога & Копыта>")
        text = build_movement_text(
            request_obj=req, kind=EXPENSE, from_wallet=self.main, destination=None, balances=self._balances()
        )
        self.assertIn("ООО &lt;Рога &amp; Копыта&gt;", text)
        self.assertNotIn("<Рога", text)

    def test_empty_fields_dash(self):
        req = self.make_request(payment_purpose="", vendor="", description="", category="", company_payer="")
        text = build_movement_text(
            request_obj=req, kind=EXPENSE, from_wallet=self.main, destination=None, balances=self._balances()
        )
        self.assertIn("📝 <b>Назначение платежа:</b>\n—\n", text)
        self.assertIn("👤 <b>Получатель:</b> —\n", text)
        self.assertIn("💬 <b>Комментарий:</b>\n—\n", text)
        self.assertIn("💳 <b>Категория:</b> —\n", text)
        self.assertIn("🏢 <b>Плательщик:</b> —\n", text)

    def test_inactive_affected_register_shown_others_hidden(self):
        req = self.make_request()
        balances = self._balances(safe_active=False)
        balances[2]["anchor_is_active"] = False
        dest = TransferDestination(wallet=self.safe, amount=Decimal("1500000"), currency="UZS")
        text = build_movement_text(
            request_obj=req, kind=TRANSFER, from_wallet=self.main, destination=dest, balances=balances
        )
        self.assertIn("👉 <b>Сейф: 100 000.50 UZS</b>", text)
        self.assertNotIn("Касса USD:", text)

    def test_revenue_error_line_after_register(self):
        req = self.make_request()
        text = build_movement_text(
            request_obj=req,
            kind=TRANSFER,
            from_wallet=self.main,
            destination=None,
            balances=self._balances(),
            revenue_error="Не найдена касса-получатель «<Сейф>»",
        )
        self.assertIn(
            "🏦 <b>Касса:</b> Основная касса\n"
            "⚠️ <b>Приход в кассу-получатель не создан:</b> Не найдена касса-получатель «&lt;Сейф&gt;»\n\n"
            "💵 <b>Сумма:</b>",
            text,
        )
        self.assertNotIn("→", text)

    def test_no_revenue_error_line_by_default(self):
        req = self.make_request()
        text = build_movement_text(
            request_obj=req, kind=TRANSFER, from_wallet=self.main, destination=None, balances=self._balances()
        )
        self.assertNotIn("Приход в кассу-получатель не создан", text)
