"""POST cash-withdrawals/intercompany-receipts/: n8n creates an expected cash receipt in the УК."""

from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, CashWithdrawalFixtures, gateway_ok
from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt
from apps.modules.requests.models import Request
from apps.modules.wallets.models import CashRegister, Wallet
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="integ-test-secret", ALLOWED_HOSTS=["*"])
class N8nIntercompanyCashReceiptTests(CashWithdrawalFixtures, APITestCase):
    """self.tenant (lemonaqua.example.com, active cash_withdrawals config) plays the receiving УК."""

    def setUp(self):
        self.make_fixtures()
        self.sender = Tenant.objects.create(name="Lemonfit ONE", subdomain="lemonone", is_active=True)
        self.url = f"{settings.N8N_INTEGRATION_URL_PREFIX.rstrip('/')}/cash-withdrawals/intercompany-receipts/"
        gw_patcher = patch(GATEWAY_PATH, side_effect=gateway_ok())
        self.gw = gw_patcher.start()
        self.addCleanup(gw_patcher.stop)

    def _sender_request(self, **overrides) -> Request:
        data = {"tenant": self.sender, "payment_purpose": "Передача в УК", "amount": Decimal("25000000.00")}
        data.update(overrides)
        return self.make_request(**data)

    def _post(self, request_id, wallet_id=None, token="integ-test-secret"):
        body = {"request_id": request_id, "wallet_id": wallet_id or self.wallet.pk}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                self.url, body, format="json", HTTP_HOST=self.host, HTTP_X_N8N_INTEGRATION_TOKEN=token
            )

    def _assert_400(self, res, field):
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.data["error_type"], "validation_error")
        self.assertIn(field, res.data["errors"])
        self.assertFalse(CashWithdrawalReceipt.objects.exists())
        self.gw.assert_not_called()

    def test_creates_receipt_in_receiving_tenant(self):
        req = self._sender_request()
        res = self._post(req.pk)
        self.assertEqual(res.status_code, 201, res.content)
        receipt = CashWithdrawalReceipt.objects.get(request=req)
        self.assertEqual(
            res.data,
            {
                "id": receipt.pk,
                "status": "pending",
                "request_id": req.pk,
                "wallet_id": self.wallet.pk,
                "amount": "25000000.00",
                "currency": "UZS",
                "created": True,
            },
        )
        self.assertEqual(receipt.tenant_id, self.tenant.id)
        self.assertEqual(receipt.amount, Decimal("25000000.00"))
        self.assertEqual(self.gw.call_count, 1)  # card sent after commit
        self.assertIn("От компании: Lemonfit ONE", self.gw.call_args.kwargs["payload"]["text"])

    def test_repeat_returns_200_and_keeps_single_receipt(self):
        req = self._sender_request()
        self.assertEqual(self._post(req.pk).status_code, 201)
        res = self._post(req.pk)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(res.data["created"])
        self.assertEqual(CashWithdrawalReceipt.objects.filter(request=req).count(), 1)
        self.assertEqual(self.gw.call_count, 1)

    def test_other_wallet_for_existing_receipt_is_409(self):
        req = self._sender_request()
        self.assertEqual(self._post(req.pk).status_code, 201)
        safe = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Сейф")
        other = Wallet.objects.create(tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=safe)
        res = self._post(req.pk, wallet_id=other.pk)
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.data["code"], "conflict")
        self.assertEqual(CashWithdrawalReceipt.objects.get(request=req).wallet_id, self.wallet.pk)

    def test_not_payed_request_is_400(self):
        self._assert_400(self._post(self._sender_request(status=Request.STATUS_APPROVED).pk), "request_id")

    def test_missing_request_is_400(self):
        self._assert_400(self._post(987654321), "request_id")

    def test_same_tenant_request_is_400(self):
        self._assert_400(self._post(self.make_request().pk), "request_id")

    def test_foreign_wallet_is_400(self):
        foreign = get_or_create_cash_wallet(tenant=self.sender, currency="UZS")
        self._assert_400(self._post(self._sender_request().pk, wallet_id=foreign.pk), "wallet_id")

    def test_currency_mismatch_is_400(self):
        self._assert_400(self._post(self._sender_request(currency="USD").pk), "wallet_id")

    def test_inactive_config_is_400(self):
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        self._assert_400(self._post(self._sender_request().pk), "non_field_errors")

    def test_invalid_payload_is_400(self):
        res = self.client.post(
            self.url, {"request_id": "abc"}, format="json",
            HTTP_HOST=self.host, HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("request_id", res.data["errors"])
        self.assertIn("wallet_id", res.data["errors"])

    def test_wrong_token_is_401(self):
        req = self._sender_request()
        res = self._post(req.pk, token="wrong")
        self.assertEqual(res.status_code, 401, res.content)
        self.assertFalse(CashWithdrawalReceipt.objects.exists())
