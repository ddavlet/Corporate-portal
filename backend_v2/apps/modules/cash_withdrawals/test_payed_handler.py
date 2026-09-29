from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, PURPOSE, CashWithdrawalFixtures, gateway_ok
from apps.modules.cash_withdrawals.models import CashWithdrawalMessage, CashWithdrawalReceipt
from apps.modules.cash_withdrawals.services import create_receipt_for_request
from apps.modules.requests.status_events import dispatch_request_payed_event_handlers


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="")  # n8n PAYED handler must not hit network
class PayedHandlerTests(CashWithdrawalFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    @patch(GATEWAY_PATH)
    def test_payed_request_with_rule_creates_receipt_and_sends_card_to_group(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_request()
        with self.captureOnCommitCallbacks(execute=True):
            dispatch_request_payed_event_handlers(request_obj=req)  # proves ready() registration

        receipt = CashWithdrawalReceipt.objects.get(request=req)
        self.assertEqual(receipt.status, CashWithdrawalReceipt.Status.PENDING)
        self.assertEqual(receipt.wallet_id, self.wallet.id)
        self.assertEqual(receipt.amount, req.amount)
        self.assertEqual(gw.call_count, 1)
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "-100500")
        self.assertEqual(payload["buttons"], [[{"label": "✅ Деньги получены", "value": f"cwr:{receipt.pk}"}]])
        self.assertEqual(receipt.messages.filter(kind=CashWithdrawalMessage.Kind.CARD).count(), 1)

    @patch(GATEWAY_PATH)
    def test_without_group_card_goes_to_each_confirmer_dm(self, gw):
        gw.side_effect = gateway_ok()
        self.config.card_telegram_chat = None
        self.config.save(update_fields=["card_telegram_chat"])
        with self.captureOnCommitCallbacks(execute=True):
            receipt = create_receipt_for_request(request_obj=self.make_request())
        recipients = sorted(c.kwargs["payload"]["recipient_id"] for c in gw.call_args_list)
        self.assertEqual(recipients, ["91001", "91002"])
        self.assertEqual(receipt.messages.count(), 2)

    @patch(GATEWAY_PATH)
    def test_no_rule_no_receipt(self, gw):
        with self.captureOnCommitCallbacks(execute=True):
            result = create_receipt_for_request(request_obj=self.make_request(payment_purpose="Аренда"))
        self.assertIsNone(result)
        self.assertFalse(CashWithdrawalReceipt.objects.exists())
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_inactive_config_no_receipt(self, gw):
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertIsNone(create_receipt_for_request(request_obj=self.make_request()))
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_purpose_match_ignores_case_and_spaces(self, gw):
        gw.side_effect = gateway_ok()
        with self.captureOnCommitCallbacks(execute=True):
            receipt = create_receipt_for_request(request_obj=self.make_request(payment_purpose=f"  {PURPOSE.upper()} "))
        self.assertIsNotNone(receipt)

    @patch(GATEWAY_PATH)
    def test_repeated_payed_creates_single_receipt_and_single_card(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_request()
        with self.captureOnCommitCallbacks(execute=True):
            create_receipt_for_request(request_obj=req)
        with self.captureOnCommitCallbacks(execute=True):
            create_receipt_for_request(request_obj=req)
        self.assertEqual(CashWithdrawalReceipt.objects.filter(request=req).count(), 1)
        self.assertEqual(gw.call_count, 1)

    @patch(GATEWAY_PATH)
    def test_currency_mismatch_no_receipt_and_alert_sent(self, gw):
        gw.side_effect = gateway_ok()
        with self.captureOnCommitCallbacks(execute=True):
            result = create_receipt_for_request(request_obj=self.make_request(currency="USD"))
        self.assertIsNone(result)
        self.assertFalse(CashWithdrawalReceipt.objects.exists())
        self.assertEqual(gw.call_count, 1)
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "91000")  # alert recipient DM (no alert group)
        self.assertIn("не совпадает", payload["text"])

    @patch(GATEWAY_PATH, return_value=None)
    def test_gateway_down_keeps_pending_receipt(self, gw):
        with self.captureOnCommitCallbacks(execute=True):
            receipt = create_receipt_for_request(request_obj=self.make_request())
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, CashWithdrawalReceipt.Status.PENDING)
        self.assertEqual(receipt.messages.count(), 0)
