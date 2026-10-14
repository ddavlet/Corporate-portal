from datetime import datetime
from datetime import timezone as dt_timezone
from unittest.mock import Mock, patch

from django.db import IntegrityError
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.cash_withdrawals import formatter
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, CashWithdrawalFixtures, gateway_ok
from apps.modules.cash_withdrawals.models import CashWithdrawalMessage, CashWithdrawalReceipt, CashWithdrawalRule
from apps.modules.cashier.models import CashRevenue
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.modules.wallets.models import CashRegister, Wallet
from apps.tenants.models import TenantMembership

# The registry stores function objects captured at ready(); patching the n8n function path would not
# affect it, so the whole handler tuple is swapped for a Mock.
REGISTRY_PATH = "apps.modules.cash_withdrawals.events.RECEIPT_CONFIRMED_HANDLERS"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ReceiptCallbackTests(CashWithdrawalFixtures, APITestCase):
    def setUp(self):
        self.make_fixtures()
        self.n8n_handler = Mock(__name__="confirmed_handler")
        patcher = patch(REGISTRY_PATH, (self.n8n_handler,))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.receipt = self.make_receipt()
        tm = TelegramMessage.objects.create(
            tenant=self.tenant, recipient_id="-100500", message_id=7001, sent_at=self.receipt.created_at
        )
        CashWithdrawalMessage.objects.create(receipt=self.receipt, telegram_message=tm, kind="card")

    def _press(self, user_id, receipt_id=None):
        return self.client.post(
            "/api/messaging-gateway/webhook/",
            {
                "event": "interaction",
                "platform": "telegram",
                "payload": f"cwr:{receipt_id or self.receipt.pk}",
                "user_id": str(user_id),
                "recipient_id": "-100500",
                "message_id": 7001,
            },
            format="json",
            HTTP_HOST=self.host,
        )

    @patch(GATEWAY_PATH)
    def test_confirmer_press_creates_revenue_and_updates_card(self, gw):
        gw.side_effect = gateway_ok()
        with self.captureOnCommitCallbacks(execute=True):
            res = self._press(self.cashier.telegram_from_id)
        self.assertEqual(res.status_code, 201, res.content)

        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.status, CashWithdrawalReceipt.Status.CONFIRMED)
        self.assertEqual(self.receipt.confirmed_by_id, self.cashier.id)
        revenue = self.receipt.cash_revenue
        self.assertEqual(revenue.total_sum, self.receipt.amount)
        self.assertEqual(revenue.wallet_id, self.wallet.id)
        self.assertEqual(revenue.external_id, f"cash-{self.receipt.request_id}")
        self.assertEqual(revenue.created_by_id, self.cashier.id)
        self.assertTrue(revenue.confirmed)
        self.assertEqual(revenue.operation, "Наличные с банка Lemonfit AQUA")
        self.assertIsNotNone(revenue.source_year)

        edit_payload = gw.call_args.kwargs["payload"]
        self.assertEqual(edit_payload["message_id"], 7001)
        self.assertEqual(edit_payload["buttons"], [])
        self.assertIn("Поступило в кассу", edit_payload["text"])
        self.n8n_handler.assert_called_once()
        self.assertEqual(self.n8n_handler.call_args.kwargs["receipt"].pk, self.receipt.pk)

    @patch(GATEWAY_PATH)
    def test_revenue_source_year_is_tashkent_year(self, gw):
        # Production: cashier_cashrevenue.source_year is NOT NULL, so source_year=None made every
        # confirm fail with IntegrityError (receipt for request #8666 stayed pending).
        gw.side_effect = gateway_ok()
        new_year_in_tashkent = datetime(2026, 12, 31, 20, 0, tzinfo=dt_timezone.utc)  # 01:00 on 1 Jan in Tashkent
        with patch("apps.modules.cash_withdrawals.services.timezone.now", return_value=new_year_in_tashkent):
            with self.captureOnCommitCallbacks(execute=True):
                res = self._press(self.cashier.telegram_from_id)
        self.assertEqual(res.status_code, 201, res.content)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.cash_revenue.source_year, 2027)

    @patch(GATEWAY_PATH)
    def test_confirmer_matched_by_telegram_chat_id(self, gw):
        gw.side_effect = gateway_ok()
        self.cashier.telegram_from_id = None
        self.cashier.save(update_fields=["telegram_from_id"])
        with self.captureOnCommitCallbacks(execute=True):
            res = self._press(self.cashier.telegram_chat_id)
        self.assertEqual(res.status_code, 201, res.content)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.status, CashWithdrawalReceipt.Status.CONFIRMED)
        self.assertEqual(self.receipt.confirmed_by_id, self.cashier.id)
        self.assertTrue(CashRevenue.objects.filter(pk=self.receipt.cash_revenue_id).exists())

    @patch(GATEWAY_PATH)
    def test_outsider_press_is_denied(self, gw):
        gw.side_effect = gateway_ok()
        with self.captureOnCommitCallbacks(execute=True):
            res = self._press(self.outsider.telegram_from_id)
        self.assertEqual(res.status_code, 403)
        self.assertFalse(CashRevenue.objects.exists())
        self.assertEqual(gw.call_args.kwargs["payload"]["text"], "Нет прав на подтверждение.")
        self.n8n_handler.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_deactivated_member_is_denied(self, gw):
        gw.side_effect = gateway_ok()
        TenantMembership.objects.filter(tenant=self.tenant, user=self.cashier).update(is_active=False)
        res = self._press(self.cashier.telegram_from_id)
        self.assertEqual(res.status_code, 403)
        self.assertFalse(CashRevenue.objects.exists())

    @patch(GATEWAY_PATH)
    def test_garbage_user_id_is_denied_not_500(self, gw):
        gw.side_effect = gateway_ok()
        self.assertEqual(self._press("abc").status_code, 403)
        self.assertEqual(self._press("").status_code, 400)  # MessagingGatewayCallbackSerializer: user_id required
        self.assertFalse(CashRevenue.objects.exists())

    @patch(GATEWAY_PATH)
    def test_second_press_creates_no_second_revenue(self, gw):
        gw.side_effect = gateway_ok()
        with self.captureOnCommitCallbacks(execute=True):
            self._press(self.cashier.telegram_from_id)
        with self.captureOnCommitCallbacks(execute=True):
            res = self._press(self.accountant.telegram_from_id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(CashRevenue.objects.count(), 1)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.confirmed_by_id, self.cashier.id)
        self.assertEqual(self.n8n_handler.call_count, 1)

    @patch(GATEWAY_PATH)
    def test_revenue_goes_to_receipt_wallet_even_if_rule_changed(self, gw):
        gw.side_effect = gateway_ok()
        other_reg = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Сейф")
        other = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=other_reg
        )
        CashWithdrawalRule.objects.filter(pk=self.rule.pk).update(wallet=other)
        with self.captureOnCommitCallbacks(execute=True):
            self._press(self.cashier.telegram_from_id)
        self.assertEqual(CashRevenue.objects.get().wallet_id, self.wallet.id)

    @patch(GATEWAY_PATH)
    def test_press_still_works_when_config_disabled(self, gw):
        gw.side_effect = gateway_ok()
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        with self.captureOnCommitCallbacks(execute=True):
            res = self._press(self.cashier.telegram_from_id)
        self.assertEqual(res.status_code, 201)

    @patch(GATEWAY_PATH)
    def test_confirm_failure_replies_and_keeps_receipt_pending(self, gw):
        # Production: a lagging cashier id sequence made the CashRevenue insert hit a taken pk,
        # and the confirmer's press ended as a silent 500 — no reply, no income.
        gw.side_effect = gateway_ok()
        with patch("apps.modules.cash_withdrawals.services.CashRevenue") as revenue_model:
            revenue_model.objects.create.side_effect = IntegrityError(
                'duplicate key value violates unique constraint "cashier_cashrevenue_pkey"'
            )
            with self.captureOnCommitCallbacks(execute=True):
                res = self._press(self.cashier.telegram_from_id)
        self.assertEqual(res.status_code, 500)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.status, CashWithdrawalReceipt.Status.PENDING)
        self.assertIsNone(self.receipt.confirmed_by_id)
        self.assertFalse(CashRevenue.objects.exists())
        reply = gw.call_args.kwargs["payload"]
        self.assertEqual(reply["text"], formatter.FAILED_TEXT)
        self.assertEqual(reply["recipient_id"], "-100500")
        self.n8n_handler.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_unknown_receipt_is_404(self, gw):
        self.assertEqual(self._press(self.cashier.telegram_from_id, receipt_id=999999).status_code, 404)
