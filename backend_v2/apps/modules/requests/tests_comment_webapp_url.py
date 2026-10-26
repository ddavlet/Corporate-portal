"""
comment_webapp_url (кнопка «💬 Комментарии») must point at the tenant's own bot.

Covers:
  1. telegram_webapp_links helpers
  2. API read  — GET /api/requests/approval-config/ returns telegram_bot_username
  3. API write — PUT rejects a t.me link to another bot, normalizes a scheme-less link
"""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.modules.requests.models import RequestApprovalConfig
from apps.modules.requests.telegram_webapp_links import (
    normalize_tme_url,
    tenant_bot_mismatch_error,
    tme_bot_username,
)
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

URL = "/api/requests/approval-config/"


class TelegramWebappLinksTests(SimpleTestCase):
    def test_tme_bot_username(self):
        self.assertEqual(tme_bot_username("https://t.me/acme_bot/comments"), "acme_bot")
        self.assertEqual(tme_bot_username("https://telegram.me/acme_bot?startapp=x"), "acme_bot")
        self.assertEqual(tme_bot_username("https://t.me/"), "")
        self.assertIsNone(tme_bot_username("https://acme.example.com/tg/comments"))

    def test_normalize_tme_url_adds_scheme_only_to_tme(self):
        self.assertEqual(normalize_tme_url("t.me/acme_bot/comments"), "https://t.me/acme_bot/comments")
        self.assertEqual(normalize_tme_url(" https://t.me/acme_bot/c "), "https://t.me/acme_bot/c")
        self.assertEqual(normalize_tme_url("acme.example.com/x"), "acme.example.com/x")
        self.assertEqual(normalize_tme_url(""), "")

    def test_mismatch_error(self):
        tenant = Tenant(name="Acme", subdomain="acme", telegram_bot_username="@Acme_Bot")
        self.assertIsNone(tenant_bot_mismatch_error(url="https://t.me/acme_bot/comments", tenant=tenant))
        self.assertIsNone(tenant_bot_mismatch_error(url="https://acme.example.com/tg", tenant=tenant))
        self.assertIn("@other_bot", tenant_bot_mismatch_error(url="https://t.me/other_bot/comments", tenant=tenant))
        self.assertIsNotNone(tenant_bot_mismatch_error(url="https://t.me/", tenant=tenant))

    def test_no_check_without_tenant_bot(self):
        tenant = Tenant(name="Acme", subdomain="acme", telegram_bot_username="")
        self.assertIsNone(tenant_bot_mismatch_error(url="https://t.me/other_bot/comments", tenant=tenant))


class CommentWebappUrlApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Acme", subdomain="acme", is_active=True, telegram_bot_username="acme_bot"
        )
        self.admin = User.objects.create_user(username="admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "acme.example.com"
        self.client.force_authenticate(self.admin)

    def _put(self, comment_webapp_url):
        return self.client.put(
            URL,
            {"comment_webapp_url": comment_webapp_url, "payment_types": []},
            format="json",
            HTTP_HOST=self.host,
        )

    def test_get_returns_tenant_bot_username(self):
        res = self.client.get(URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["telegram_bot_username"], "acme_bot")

    def test_put_rejects_link_to_another_bot(self):
        res = self._put("https://t.me/other_bot/comments")
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("comment_webapp_url", res.data)
        self.assertFalse(
            RequestApprovalConfig.objects.filter(tenant=self.tenant).exclude(comment_webapp_url="").exists()
        )

    def test_put_accepts_tenant_bot_link_case_insensitive(self):
        res = self._put("https://t.me/Acme_Bot/comments")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["comment_webapp_url"], "https://t.me/Acme_Bot/comments")
        self.assertEqual(res.data["telegram_bot_username"], "acme_bot")

    def test_put_normalizes_scheme_less_link(self):
        res = self._put("t.me/acme_bot/comments")
        self.assertEqual(res.status_code, 200, res.content)
        cfg = RequestApprovalConfig.objects.get(tenant=self.tenant)
        self.assertEqual(cfg.comment_webapp_url, "https://t.me/acme_bot/comments")

    def test_put_allows_any_link_when_tenant_has_no_bot(self):
        self.tenant.telegram_bot_username = ""
        self.tenant.save(update_fields=["telegram_bot_username"])
        res = self._put("https://t.me/other_bot/comments")
        self.assertEqual(res.status_code, 200, res.content)

    def test_put_allows_empty_link(self):
        res = self._put("")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["comment_webapp_url"], "")
