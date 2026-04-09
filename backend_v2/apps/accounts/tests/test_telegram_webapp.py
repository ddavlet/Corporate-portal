import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.telegram_webapp import TelegramWebAppDataError, validate_webapp_init_data
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


def _signed_init_data(*, bot_token: str, user_id: int, auth_date: int | None = None) -> str:
    """Build a valid initData query string (same algorithm as Telegram Web Apps)."""
    if auth_date is None:
        auth_date = int(time.time())
    user_json = json.dumps({"id": user_id, "first_name": "Test"})
    fields = {"auth_date": str(auth_date), "user": user_json}
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    sig_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    fields["hash"] = sig_hash
    return urlencode(fields)


def _signed_init_data_with_signature_field(*, bot_token: str, user_id: int, auth_date: int | None = None) -> str:
    """initData как у новых клиентов: есть `signature`, а HMAC `hash` считается по всем полям кроме hash."""
    if auth_date is None:
        auth_date = int(time.time())
    user_json = json.dumps({"id": user_id, "first_name": "Test"})
    fields = {
        "auth_date": str(auth_date),
        "user": user_json,
        "signature": "dGVzdC1zaWduYXR1cmU",
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    sig_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    fields["hash"] = sig_hash
    return urlencode(fields)


class ValidateWebappInitDataTests(TestCase):
    def test_valid_round_trip(self):
        token = "123456:ABC-DEF_fake_token_for_tests"
        init = _signed_init_data(bot_token=token, user_id=999001)
        flat = validate_webapp_init_data(init, token)
        self.assertIn("user", flat)
        self.assertIn("auth_date", flat)
        user = json.loads(flat["user"])
        self.assertEqual(user["id"], 999001)

    def test_wrong_token_fails(self):
        token = "123456:ABC-DEF_fake_token_for_tests"
        init = _signed_init_data(bot_token=token, user_id=1)
        with self.assertRaises(TelegramWebAppDataError):
            validate_webapp_init_data(init, "other_token")

    def test_valid_when_hash_includes_signature_field(self):
        token = "123456:ABC-DEF_fake_token_for_tests"
        init = _signed_init_data_with_signature_field(bot_token=token, user_id=999002)
        flat = validate_webapp_init_data(init, token)
        self.assertNotIn("signature", flat)
        self.assertEqual(json.loads(flat["user"])["id"], 999002)

    def test_expired_auth_date(self):
        token = "123456:ABC-DEF_fake_token_for_tests"
        old = int(time.time()) - 200_000
        init = _signed_init_data(bot_token=token, user_id=1, auth_date=old)
        with self.assertRaises(TelegramWebAppDataError):
            validate_webapp_init_data(init, token, max_age_seconds=86400)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TelegramWebAppAuthViewTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.tenant.set_telegram_bot_token("123456:TEST_BOT_TOKEN_FOR_WEBAPP")
        self.tenant.save(update_fields=["telegram_bot_token_enc"])

        self.user_linked = User.objects.create_user(username="tg_user", password="x")
        self.user_linked.telegram_from_id = 424242
        self.user_linked.save(update_fields=["telegram_from_id"])

        self.user_no_tg = User.objects.create_user(username="plain", password="x")

        for u in (self.user_linked, self.user_no_tg):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.user_linked, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user_no_tg, role=TenantUserRole.ROLE_REQUESTER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        self.host = "acme.example.com"

    def test_403_when_user_not_linked_to_telegram(self):
        init = _signed_init_data(
            bot_token=self.tenant.get_telegram_bot_token(),
            user_id=999999,
        )
        res = self.client.post(
            "/api/auth/telegram/webapp/",
            {"init_data": init},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 403)

    def test_200_returns_jwt_when_linked(self):
        init = _signed_init_data(
            bot_token=self.tenant.get_telegram_bot_token(),
            user_id=424242,
        )
        res = self.client.post(
            "/api/auth/telegram/webapp/",
            {"init_data": init},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertEqual(res.data.get("username"), "tg_user")

    def test_409_when_telegram_id_linked_to_multiple_users(self):
        duplicate = User.objects.create_user(username="tg_user_duplicate", password="x")
        duplicate.telegram_from_id = 424242
        duplicate.save(update_fields=["telegram_from_id"])
        TenantMembership.objects.create(tenant=self.tenant, user=duplicate, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=duplicate, role=TenantUserRole.ROLE_REQUESTER)

        init = _signed_init_data(
            bot_token=self.tenant.get_telegram_bot_token(),
            user_id=424242,
        )
        res = self.client.post(
            "/api/auth/telegram/webapp/",
            {"init_data": init},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(
            res.data.get("detail"),
            "Telegram account is linked to multiple users in this organization.",
        )
