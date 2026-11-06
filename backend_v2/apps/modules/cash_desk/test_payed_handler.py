from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.modules.cash_desk.constants import TRANSFER_PURPOSE
from apps.modules.cash_desk.fixtures import CashDeskFixtures
from apps.modules.cash_desk.models import CashDeskMessage, CashRegisterTransferTarget
from apps.modules.cash_desk.services import SAME_WALLET_ERROR, on_request_payed
from apps.modules.cash_desk.transfer_revenue import STALE_TARGET_ERROR
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, gateway_ok
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.requests.models import Request
from apps.modules.requests.status_events import dispatch_request_payed_event_handlers


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="")  # n8n PAYED handler must not hit network
class CashDeskPayedHandlerTests(CashDeskFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _expense(self, req, wallet):
        now = datetime(2026, 11, 6, 7, 0, tzinfo=dt_timezone.utc)
        return CashExpense.objects.create(
            tenant=self.tenant,
            external_id=f"req-{req.id}",
            confirmed=True,
            title=req.title,
            amount=req.amount,
            currency=req.currency,
            expense_at=now,
            expense_year=2026,
            expense_month=11,
            expense_day=6,
            note=req.description,
            payload={"request_id": req.id, "source": "request_payment_create"},
            created_by=self.admin,
            wallet=wallet,
        )

    def _pay(self, req):
        with self.captureOnCommitCallbacks(execute=True):
            on_request_payed(request_obj=req)

    def _transfer_request(self, **kw):
        data = {"payment_purpose": TRANSFER_PURPOSE, "wallet_ref": self.main}
        data.update(kw)
        return self.make_request(**data)

    @patch(GATEWAY_PATH)
    def test_cash_expense_sends_one_message(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_request()
        with self.captureOnCommitCallbacks(execute=True):
            dispatch_request_payed_event_handlers(request_obj=req)  # proves ready() registration

        self.assertEqual(gw.call_count, 1)
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "-100500")
        self.assertIn("Расход", payload["text"])
        self.assertIn("Основная касса", payload["text"])
        msg = CashDeskMessage.objects.get(request=req)
        self.assertEqual(msg.kind, CashDeskMessage.Kind.EXPENSE)
        self.assertEqual(msg.status, CashDeskMessage.Status.SENT)
        self.assertIsNotNone(msg.telegram_message_id)
        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant).exists())

    @patch(GATEWAY_PATH)
    def test_invest_cash_uses_expense_wallet(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_request(payment_type="Инвест. наличные")
        self._expense(req, self.safe)
        self._pay(req)

        self.assertEqual(gw.call_count, 1)
        self.assertIn("🏦 <b>Касса:</b> Сейф", gw.call_args.kwargs["payload"]["text"])
        self.assertEqual(CashDeskMessage.objects.get(request=req).status, CashDeskMessage.Status.SENT)

    @patch(GATEWAY_PATH)
    def test_without_cash_expense_falls_back_to_default_register(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_request(wallet_ref=None)
        self._pay(req)

        self.assertIn("🏦 <b>Касса:</b> Основная касса", gw.call_args.kwargs["payload"]["text"])

    @patch(GATEWAY_PATH)
    def test_transfer_creates_revenue_and_message(self, gw):
        gw.side_effect = gateway_ok()
        req = self._transfer_request()
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant, request=req, to_wallet=self.safe, to_amount=req.amount
        )
        self._pay(req)

        revenue = CashRevenue.objects.get(tenant=self.tenant, external_id=f"cash-{req.id}")
        self.assertEqual(revenue.wallet_id, self.safe.id)
        self.assertEqual(revenue.total_sum, Decimal("1500000.00"))
        self.assertEqual(revenue.currency, "UZS")
        self.assertEqual(gw.call_count, 1)
        text = gw.call_args.kwargs["payload"]["text"]
        self.assertIn("Перемещение", text)
        self.assertIn("Основная касса → Сейф", text)
        msg = CashDeskMessage.objects.get(request=req)
        self.assertEqual(msg.kind, CashDeskMessage.Kind.TRANSFER)
        self.assertEqual(msg.status, CashDeskMessage.Status.SENT)
        self.assertEqual(msg.revenue_error, "")

    @patch(GATEWAY_PATH)
    def test_transfer_unresolved_still_sends_and_logs(self, gw):
        gw.side_effect = gateway_ok()
        req = self._transfer_request(description="Без строки назначения")
        with self.assertLogs("apps.modules.cash_desk.services", level="ERROR"):
            self._pay(req)

        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant, external_id=f"cash-{req.id}").exists())
        msg = CashDeskMessage.objects.get(request=req)
        self.assertNotEqual(msg.revenue_error, "")
        self.assertEqual(msg.status, CashDeskMessage.Status.SENT)
        self.assertEqual(gw.call_count, 1)
        self.assertIn("Перемещение", gw.call_args.kwargs["payload"]["text"])

    @patch(GATEWAY_PATH)
    def test_transfer_same_currency_amount_edited_after_target_uses_new_amount(self, gw):
        gw.side_effect = gateway_ok()
        req = self._transfer_request()
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.safe,
            to_amount=req.amount,
            source_amount=req.amount,
            source_currency=req.currency,
        )
        Request.objects.filter(pk=req.pk).update(amount=Decimal("1750000.00"))
        req.refresh_from_db()
        self._pay(req)

        revenue = CashRevenue.objects.get(tenant=self.tenant, external_id=f"cash-{req.id}")
        self.assertEqual(revenue.wallet_id, self.safe.id)
        self.assertEqual(revenue.total_sum, Decimal("1750000.00"))
        self.assertEqual(CashDeskMessage.objects.get(request=req).revenue_error, "")

    @patch(GATEWAY_PATH)
    def test_transfer_cross_currency_unchanged_uses_to_amount(self, gw):
        gw.side_effect = gateway_ok()
        req = self._transfer_request()
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.usd,
            to_amount=Decimal("120.50"),
            source_amount=req.amount,
            source_currency=req.currency,
        )
        self._pay(req)

        revenue = CashRevenue.objects.get(tenant=self.tenant, external_id=f"cash-{req.id}")
        self.assertEqual(revenue.wallet_id, self.usd.id)
        self.assertEqual(revenue.total_sum, Decimal("120.50"))
        self.assertEqual(revenue.currency, "USD")
        self.assertEqual(CashDeskMessage.objects.get(request=req).revenue_error, "")

    @patch(GATEWAY_PATH)
    def test_transfer_cross_currency_amount_changed_no_revenue(self, gw):
        gw.side_effect = gateway_ok()
        req = self._transfer_request()
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.usd,
            to_amount=Decimal("120.50"),
            source_amount=req.amount,
            source_currency=req.currency,
        )
        Request.objects.filter(pk=req.pk).update(amount=Decimal("1750000.00"))
        req.refresh_from_db()
        with self.assertLogs("apps.modules.cash_desk.services", level="ERROR"):
            self._pay(req)

        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant, external_id=f"cash-{req.id}").exists())
        msg = CashDeskMessage.objects.get(request=req)
        self.assertEqual(msg.revenue_error, STALE_TARGET_ERROR)
        self.assertEqual(msg.status, CashDeskMessage.Status.SENT)
        self.assertEqual(gw.call_count, 1)

    @patch(GATEWAY_PATH)
    def test_transfer_destination_equals_source_no_revenue(self, gw):
        gw.side_effect = gateway_ok()
        req = self._transfer_request(wallet_ref=self.safe)
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.main,
            to_amount=req.amount,
            source_amount=req.amount,
            source_currency=req.currency,
        )
        self._expense(req, self.main)  # cash actually paid from the destination register
        with self.assertLogs("apps.modules.cash_desk.services", level="ERROR"):
            self._pay(req)

        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant, external_id=f"cash-{req.id}").exists())
        msg = CashDeskMessage.objects.get(request=req)
        self.assertEqual(msg.revenue_error, SAME_WALLET_ERROR)
        self.assertEqual(msg.status, CashDeskMessage.Status.SENT)
        self.assertEqual(gw.call_count, 1)

    @patch(GATEWAY_PATH)
    def test_repeat_payed_sends_once(self, gw):
        gw.side_effect = gateway_ok()
        req = self._transfer_request()
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant, request=req, to_wallet=self.safe, to_amount=req.amount
        )
        self._pay(req)
        self._pay(req)

        self.assertEqual(gw.call_count, 1)
        self.assertEqual(CashDeskMessage.objects.filter(request=req).count(), 1)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant, external_id=f"cash-{req.id}").count(), 1)

    @patch(GATEWAY_PATH)
    def test_inactive_config_does_nothing(self, gw):
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        req = self._transfer_request()
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant, request=req, to_wallet=self.safe, to_amount=req.amount
        )
        self._pay(req)

        gw.assert_not_called()
        self.assertFalse(CashDeskMessage.objects.exists())
        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant).exists())

    @patch(GATEWAY_PATH)
    def test_active_without_chat_creates_revenue_only(self, gw):
        self.config.telegram_chat = None
        self.config.save(update_fields=["telegram_chat"])
        req = self._transfer_request()
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant, request=req, to_wallet=self.safe, to_amount=req.amount
        )
        self._pay(req)

        gw.assert_not_called()
        self.assertTrue(CashRevenue.objects.filter(tenant=self.tenant, external_id=f"cash-{req.id}").exists())
        msg = CashDeskMessage.objects.get(request=req)
        self.assertEqual(msg.status, CashDeskMessage.Status.SKIPPED)
        self.assertEqual(msg.error, "Кассовая группа не выбрана")

    @patch(GATEWAY_PATH)
    def test_gateway_failure_marks_failed(self, gw):
        gw.side_effect = Exception("gateway down")
        req = self.make_request()
        self._pay(req)  # must not raise

        msg = CashDeskMessage.objects.get(request=req)
        self.assertEqual(msg.status, CashDeskMessage.Status.FAILED)
        self.assertIn("gateway down", msg.error)
        self.assertIsNone(msg.telegram_message_id)

    @patch(GATEWAY_PATH)
    def test_gateway_without_message_id_marks_failed(self, gw):
        gw.return_value = None
        req = self.make_request()
        self._pay(req)

        msg = CashDeskMessage.objects.get(request=req)
        self.assertEqual(msg.status, CashDeskMessage.Status.FAILED)
        self.assertEqual(msg.error, "Шлюз не вернул message_id")

    @patch(GATEWAY_PATH)
    def test_non_cash_ignored(self, gw):
        req = self.make_request(payment_type="Перечисление")
        self._pay(req)

        gw.assert_not_called()
        self.assertFalse(CashDeskMessage.objects.exists())
