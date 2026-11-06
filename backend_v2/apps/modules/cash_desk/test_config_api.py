from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.cash_desk.fixtures import CashDeskFixtures
from apps.modules.cash_desk.models import CashDeskConfig
from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

URL = "/api/cash-desk/config/"
User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ConfigApiTests(CashDeskFixtures, APITestCase):
    def setUp(self):
        self.make_fixtures()
        self.client.force_authenticate(self.admin)

    def test_get_returns_defaults_and_active_chats(self):
        CashDeskConfig.objects.filter(tenant=self.tenant).delete()
        TenantTelegramChat.objects.create(
            tenant=self.tenant, name="Старый чат", chat_id="-100501", is_active=False, created_by=self.admin
        )
        res = self.client.get(URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["is_active"])
        self.assertIsNone(res.data["telegram_chat_id"])
        self.assertEqual(res.data["options"]["telegram_chats"], [{"id": self.group.id, "name": "Касса Aqua"}])

    def test_put_saves_config(self):
        CashDeskConfig.objects.filter(tenant=self.tenant).delete()
        res = self.client.put(
            URL, {"is_active": True, "telegram_chat_id": self.group.id}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 200)
        config = CashDeskConfig.objects.get(tenant=self.tenant)
        self.assertTrue(config.is_active)
        self.assertEqual(config.telegram_chat_id, self.group.id)
        self.assertEqual(config.updated_by_id, self.admin.id)

    def test_put_rejects_foreign_chat(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        foreign = TenantTelegramChat.objects.create(
            tenant=other, name="Чужой", chat_id="-100999", created_by=self.admin
        )
        res = self.client.put(
            URL, {"is_active": True, "telegram_chat_id": foreign.id}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("telegram_chat_id", res.data)

    def test_non_admin_forbidden(self):
        member = User.objects.create_user(username="cd-requester", password="x", full_name="Рядовой")
        TenantMembership.objects.create(tenant=self.tenant, user=member, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=member, role=TenantUserRole.ROLE_REQUESTER)
        self.client.force_authenticate(member)
        res = self.client.get(URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 403)
