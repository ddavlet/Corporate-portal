import hashlib
import hmac
import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.telegram_login_widget import (
    TelegramLoginWidgetDataError,
    validate_login_widget_auth_data,
)
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


def _signed_auth_data(*, bot_token: str, user_id: int, auth_date: int | None = None) -> dict[str, str]:
    if auth_date is None:
        auth_date = int(time.time())
    fields = {
        "id": str(user_id),
        "first_name": "Test",
        "username": "telegram_user",
        "auth_date": str(auth_date),
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    sig_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return {**fields, "hash": sig_hash}


class ValidateTelegramLoginWidgetDataTests(TestCase):
    def test_valid_round_trip(self):
        token = "123456:ABC-DEF_fake_token_for_tests"
        auth_data = _signed_auth_data(bot_token=token, user_id=999001)
        fields = validate_login_widget_auth_data(auth_data, token)
        self.assertEqual(fields["id"], "999001")
        self.assertEqual(fields["username"], "telegram_user")

    def test_wrong_token_fails(self):
        token = "123456:ABC-DEF_fake_token_for_tests"
        auth_data = _signed_auth_data(bot_token=token, user_id=1)
        with self.assertRaises(TelegramLoginWidgetDataError):
            validate_login_widget_auth_data(auth_data, "other_token")

    def test_expired_auth_date(self):
        token = "123456:ABC-DEF_fake_token_for_tests"
        old = int(time.time()) - 200_000
        auth_data = _signed_auth_data(bot_token=token, user_id=1, auth_date=old)
        with self.assertRaises(TelegramLoginWidgetDataError):
            validate_login_widget_auth_data(auth_data, token, max_age_seconds=86400)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TelegramLoginWidgetAuthViewTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True, telegram_bot_username="acme_bot")
        self.tenant.set_telegram_bot_token("123456:TEST_BOT_TOKEN_FOR_WIDGET")
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

    def test_get_returns_bot_username(self):
        res = self.client.get("/api/auth/telegram/login-widget/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.get("bot_username"), "acme_bot")

    def test_403_when_user_not_linked_to_telegram(self):
        auth_data = _signed_auth_data(bot_token=self.tenant.get_telegram_bot_token(), user_id=999999)
        res = self.client.post(
            "/api/auth/telegram/login-widget/",
            {"auth_data": auth_data},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 403)

    def test_200_returns_jwt_when_linked(self):
        auth_data = _signed_auth_data(bot_token=self.tenant.get_telegram_bot_token(), user_id=424242)
        res = self.client.post(
            "/api/auth/telegram/login-widget/",
            {"auth_data": auth_data},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertEqual(res.data.get("username"), "tg_user")

    def test_400_for_invalid_hash(self):
        auth_data = _signed_auth_data(bot_token=self.tenant.get_telegram_bot_token(), user_id=424242)
        auth_data["hash"] = "bad_hash"
        res = self.client.post(
            "/api/auth/telegram/login-widget/",
            {"auth_data": auth_data},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)

    def test_409_when_telegram_id_linked_to_multiple_users(self):
        duplicate = User.objects.create_user(username="tg_user_duplicate", password="x")
        duplicate.telegram_from_id = 424242
        duplicate.save(update_fields=["telegram_from_id"])
        TenantMembership.objects.create(tenant=self.tenant, user=duplicate, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=duplicate, role=TenantUserRole.ROLE_REQUESTER)

        auth_data = _signed_auth_data(bot_token=self.tenant.get_telegram_bot_token(), user_id=424242)
        res = self.client.post(
            "/api/auth/telegram/login-widget/",
            {"auth_data": auth_data},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 409)
