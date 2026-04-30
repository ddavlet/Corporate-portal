"""OTP sends via messaging gateway; bot token from tenant or TELEGRAM_BOT_TOKEN fallback."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class OtpMessagingGatewayTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Acme",
            subdomain="acme",
            is_active=True,
            telegram_otp_enabled=True,
        )
        self.tenant.set_telegram_bot_token("123456:OTP_TEST_BOT_TOKEN")
        self.tenant.save(update_fields=["telegram_bot_token_enc"])

        self.user = User.objects.create_user(username="otp_user", password="x")
        self.user.telegram_chat_id = 777001
        self.user.save(update_fields=["telegram_chat_id"])

        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER)

    def _host(self):
        return {"HTTP_HOST": "acme.example.com"}

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_otp_request_uses_messaging_gateway_send_payload(self, gw_mock):
        gw_mock.return_value = {"ok": True, "message_id": 42}

        res = self.client.post(
            "/api/auth/otp/request/",
            {"username": "otp_user"},
            format="json",
            **self._host(),
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        gw_mock.assert_called_once()
        kwargs = gw_mock.call_args.kwargs
        self.assertEqual(kwargs["tenant"], self.tenant)
        payload = kwargs["payload"]
        self.assertEqual(payload["action"], "send")
        self.assertEqual(payload["recipient_id"], "777001")
        self.assertEqual(payload["format"], "html")
        self.assertEqual(payload["bot_token"], "123456:OTP_TEST_BOT_TOKEN")
        self.assertIn("<code>", payload["text"])

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_otp_request_returns_503_when_gateway_fails(self, gw_mock):
        gw_mock.return_value = None

        res = self.client.post(
            "/api/auth/otp/request/",
            {"username": "otp_user"},
            format="json",
            **self._host(),
        )
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE, res.content)
