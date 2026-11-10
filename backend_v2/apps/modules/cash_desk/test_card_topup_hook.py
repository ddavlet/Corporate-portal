from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.modules.cash_desk import card_topup
from apps.modules.cash_desk.card_topup import NO_MESSAGE_ID_ERROR, NO_TELEGRAM_ERROR, on_request_payed
from apps.modules.cash_desk.card_topup_fixtures import CardTopupFixtures, make_card_wallet
from apps.modules.cash_desk.models import CardTopupNotification, CashDeskMessage
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, gateway_ok
from apps.modules.requests.status_events import dispatch_request_payed_event_handlers
from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.tenants.models import Tenant, TenantMembership


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="")  # n8n PAYED handler must not hit network
class CardTopupHookTests(CardTopupFixtures, TestCase):
    def setUp(self):
        self.make_topup_fixtures()

    def _pay(self, req):
        with self.captureOnCommitCallbacks(execute=True):
            on_request_payed(request_obj=req)

    def _texts_by_recipient(self, gw) -> dict:
        return {c.kwargs["payload"]["recipient_id"]: c.kwargs["payload"]["text"] for c in gw.call_args_list}

    @patch(GATEWAY_PATH)
    def test_sends_personal_message_after_commit(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_topup_request()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            dispatch_request_payed_event_handlers(request_obj=req)  # proves ready() registration
        self.assertNotIn("93001", self._texts_by_recipient(gw))  # nothing is sent before commit
        self.assertEqual(
            CardTopupNotification.objects.get(request=req).status, CardTopupNotification.Status.PENDING
        )
        for callback in callbacks:
            callback()

        calls = [c for c in gw.call_args_list if c.kwargs["payload"]["recipient_id"] == "93001"]
        self.assertEqual(len(calls), 1)
        text = calls[0].kwargs["payload"]["text"]
        self.assertIn("🔄 <b>Вид движения:</b> Пополнение корпоративной карты", text)
        self.assertIn("💵 <b>Сумма:</b> <code>5 000 000 UZS</code>", text)
        self.assertIn("💳 <b>Карта:</b> Humo Neuron", text)
        self.assertIn("💰 <b>Остаток на карте:</b> <code>2 500 000 UZS</code>", text)
        notification = CardTopupNotification.objects.get(request=req, recipient=self.accountant)
        self.assertEqual(notification.status, CardTopupNotification.Status.SENT)
        self.assertIsNotNone(notification.telegram_message_id)
        self.assertFalse(CashDeskMessage.objects.filter(request=req).exists())

    @patch(GATEWAY_PATH)
    def test_sends_to_each_recipient(self, gw):
        gw.side_effect = gateway_ok()
        self.topup_config.recipients.add(self.admin)
        req = self.make_topup_request()
        self._pay(req)

        self.assertEqual(set(self._texts_by_recipient(gw)), {"92000", "93001"})
        self.assertEqual(
            CardTopupNotification.objects.filter(request=req, status=CardTopupNotification.Status.SENT).count(), 2
        )

    @patch(GATEWAY_PATH)
    def test_uses_wallet_ref_card(self, gw):
        gw.side_effect = gateway_ok()
        other = make_card_wallet(self.tenant, label="Visa USD", currency="USD", opening_balance="120.50")
        req = self.make_topup_request(wallet_ref=other)
        self._pay(req)

        text = gw.call_args.kwargs["payload"]["text"]
        self.assertIn("💳 <b>Карта:</b> Visa USD", text)
        self.assertIn("💰 <b>Остаток на карте:</b> <code>120.50 USD</code>", text)

    @patch(GATEWAY_PATH)
    def test_non_card_wallet_ref_falls_back_to_first_card(self, gw):
        gw.side_effect = gateway_ok()
        make_card_wallet(self.tenant, label="Вторая карта")
        req = self.make_topup_request(wallet_ref=self.main)  # cash wallet, not a card
        self._pay(req)

        self.assertIn("💳 <b>Карта:</b> Humo Neuron", gw.call_args.kwargs["payload"]["text"])

    @patch(GATEWAY_PATH)
    def test_card_label_empty_uses_currency(self, gw):
        gw.side_effect = gateway_ok()
        self.card.corporate_card_account.label = "  "
        self.card.corporate_card_account.save(update_fields=["label"])
        req = self.make_topup_request()
        self._pay(req)

        self.assertIn("💳 <b>Карта:</b> UZS", gw.call_args.kwargs["payload"]["text"])

    @patch(GATEWAY_PATH)
    def test_without_card_omits_card_lines(self, gw):
        gw.side_effect = gateway_ok()
        other_tenant = Tenant.objects.create(name="Other", subdomain="other-ct", is_active=True)
        self.card.corporate_card_account.tenant = other_tenant
        self.card.corporate_card_account.save(update_fields=["tenant"])
        self.card.tenant = other_tenant
        self.card.save(update_fields=["tenant"])
        req = self.make_topup_request()
        self._pay(req)

        text = gw.call_args.kwargs["payload"]["text"]
        self.assertNotIn("Карта:", text)
        self.assertNotIn("Остаток на карте", text)
        self.assertEqual(
            CardTopupNotification.objects.get(request=req).status, CardTopupNotification.Status.SENT
        )

    @patch(GATEWAY_PATH)
    def test_non_topup_request_ignored(self, gw):
        for payment_type in ("Наличные", "Перечисление"):
            self._pay(self.make_topup_request(payment_type=payment_type))
        self.assertFalse(CardTopupNotification.objects.exists())
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_inactive_config_does_nothing(self, gw):
        self.topup_config.is_active = False
        self.topup_config.save(update_fields=["is_active"])
        self._pay(self.make_topup_request())

        gw.assert_not_called()
        self.assertFalse(CardTopupNotification.objects.exists())

    @patch(GATEWAY_PATH)
    def test_no_recipients_does_nothing(self, gw):
        self.topup_config.recipients.clear()
        self._pay(self.make_topup_request())

        gw.assert_not_called()
        self.assertFalse(CardTopupNotification.objects.exists())

    @patch(GATEWAY_PATH)
    def test_inactive_member_is_not_notified(self, gw):
        TenantMembership.objects.filter(tenant=self.tenant, user=self.accountant).update(is_active=False)
        self._pay(self.make_topup_request())

        gw.assert_not_called()
        self.assertFalse(CardTopupNotification.objects.exists())

    @patch(GATEWAY_PATH)
    def test_repeated_payed_does_not_resend(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_topup_request()
        self._pay(req)
        self._pay(req)

        self.assertEqual(gw.call_count, 1)
        self.assertEqual(CardTopupNotification.objects.filter(request=req).count(), 1)

    @patch(GATEWAY_PATH)
    def test_recipient_without_telegram_skipped(self, gw):
        gw.side_effect = gateway_ok()
        self.topup_config.recipients.add(self.no_tg)
        req = self.make_topup_request()
        self._pay(req)

        self.assertEqual(gw.call_count, 1)
        skipped = CardTopupNotification.objects.get(request=req, recipient=self.no_tg)
        self.assertEqual(skipped.status, CardTopupNotification.Status.SKIPPED)
        self.assertEqual(skipped.error, NO_TELEGRAM_ERROR)
        self.assertEqual(
            CardTopupNotification.objects.get(request=req, recipient=self.accountant).status,
            CardTopupNotification.Status.SENT,
        )

    def test_send_returning_none_marks_failed(self):
        req = self.make_topup_request()
        with patch.object(TelegramDispatcher, "send", return_value=None) as send:
            self._pay(req)

        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["recipient_id"], "93001")
        notification = CardTopupNotification.objects.get(request=req)
        self.assertEqual(notification.status, CardTopupNotification.Status.FAILED)
        self.assertEqual(notification.error, NO_MESSAGE_ID_ERROR)

    def test_send_exception_marks_failed_and_continues(self):
        self.topup_config.recipients.add(self.admin)
        req = self.make_topup_request()
        with patch.object(TelegramDispatcher, "send", side_effect=RuntimeError("gateway down")) as send:
            self._pay(req)  # must not raise

        self.assertEqual(send.call_count, 2)
        statuses = set(CardTopupNotification.objects.filter(request=req).values_list("status", flat=True))
        self.assertEqual(statuses, {CardTopupNotification.Status.FAILED})
        self.assertIn("gateway down", CardTopupNotification.objects.filter(request=req).first().error)

    def test_hook_db_error_never_propagates(self):
        req = self.make_topup_request()
        with patch.object(card_topup, "active_recipients", side_effect=RuntimeError("db broken")):
            with self.assertLogs("apps.modules.cash_desk.card_topup", level="ERROR"):
                self._pay(req)  # must not raise
        self.assertFalse(CardTopupNotification.objects.exists())

    def test_text_build_error_marks_failed(self):
        req = self.make_topup_request()
        with patch.object(card_topup, "card_payload", side_effect=RuntimeError("balance broken")):
            self._pay(req)  # must not raise
        notification = CardTopupNotification.objects.get(request=req)
        self.assertEqual(notification.status, CardTopupNotification.Status.FAILED)
        self.assertIn("balance broken", notification.error)
