from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.cash_desk.card_topup_fixtures import CardTopupFixtures
from apps.modules.cash_desk.models import CardTopupNotifyConfig
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

URL = "/api/cash-desk/card-topup/config/"
User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class CardTopupConfigApiTests(CardTopupFixtures, APITestCase):
    def setUp(self):
        self.make_topup_fixtures()
        self.client.force_authenticate(self.admin)

    def _put(self, body):
        return self.client.put(URL, body, format="json", HTTP_HOST=self.host)

    def test_get_returns_config_and_active_members(self):
        inactive = User.objects.create_user(username="ct-inactive", password="x", full_name="Уволенный")
        TenantMembership.objects.create(tenant=self.tenant, user=inactive, is_active=False)
        res = self.client.get(URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["is_active"])
        self.assertEqual(res.data["recipient_ids"], [self.accountant.id])
        users = {u["id"]: u for u in res.data["available_users"]}
        self.assertEqual(set(users), {self.admin.id, self.accountant.id, self.no_tg.id})
        self.assertEqual(users[self.accountant.id], {"id": self.accountant.id, "name": "Илхом Уктамов", "has_telegram": True})
        self.assertFalse(users[self.no_tg.id]["has_telegram"])

    def test_get_defaults_without_config(self):
        CardTopupNotifyConfig.objects.filter(tenant=self.tenant).delete()
        res = self.client.get(URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["is_active"])
        self.assertEqual(res.data["recipient_ids"], [])

    def test_put_saves_config(self):
        CardTopupNotifyConfig.objects.filter(tenant=self.tenant).delete()
        res = self._put({"is_active": True, "recipient_ids": [self.no_tg.id, self.admin.id, self.admin.id]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["recipient_ids"], sorted([self.no_tg.id, self.admin.id]))
        config = CardTopupNotifyConfig.objects.get(tenant=self.tenant)
        self.assertTrue(config.is_active)
        self.assertEqual(set(config.recipients.values_list("id", flat=True)), {self.no_tg.id, self.admin.id})
        self.assertEqual(config.updated_by_id, self.admin.id)

    def test_put_can_disable_and_clear(self):
        res = self._put({"is_active": False, "recipient_ids": []})
        self.assertEqual(res.status_code, 200)
        config = CardTopupNotifyConfig.objects.get(tenant=self.tenant)
        self.assertFalse(config.is_active)
        self.assertFalse(config.recipients.exists())

    def test_put_active_requires_recipient(self):
        res = self._put({"is_active": True, "recipient_ids": []})
        self.assertEqual(res.status_code, 400)
        self.assertIn("recipient_ids", res.data)

    def test_put_rejects_non_member(self):
        outsider = User.objects.create_user(username="ct-out", password="x", full_name="Чужой")
        res = self._put({"is_active": True, "recipient_ids": [outsider.id]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(str(res.data["recipient_ids"][0]), "Пользователь не состоит в компании.")

    def test_put_rejects_inactive_member(self):
        TenantMembership.objects.filter(tenant=self.tenant, user=self.no_tg).update(is_active=False)
        res = self._put({"is_active": True, "recipient_ids": [self.no_tg.id]})
        self.assertEqual(res.status_code, 400)

    def test_put_rejects_member_of_other_tenant(self):
        other = Tenant.objects.create(name="Other", subdomain="other-ct", is_active=True)
        stranger = User.objects.create_user(username="ct-stranger", password="x", full_name="Из другой компании")
        TenantMembership.objects.create(tenant=other, user=stranger, is_active=True)
        res = self._put({"is_active": True, "recipient_ids": [stranger.id]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            list(CardTopupNotifyConfig.objects.get(tenant=self.tenant).recipients.values_list("id", flat=True)),
            [self.accountant.id],
        )

    def test_tenant_isolation(self):
        other = Tenant.objects.create(name="Other", subdomain="other-ct", is_active=True)
        other_admin = User.objects.create_user(username="ct-oadmin", password="x", full_name="Админ Другой")
        TenantMembership.objects.create(tenant=other, user=other_admin, is_active=True)
        TenantUserRole.objects.create(tenant=other, user=other_admin, role=TenantUserRole.ROLE_ADMIN)
        self.client.force_authenticate(other_admin)
        res = self.client.get(URL, HTTP_HOST="other-ct.example.com")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["is_active"])
        self.assertEqual(res.data["recipient_ids"], [])
        self.assertEqual([u["id"] for u in res.data["available_users"]], [other_admin.id])

        res = self.client.put(
            URL, {"is_active": False, "recipient_ids": []}, format="json", HTTP_HOST="other-ct.example.com"
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(CardTopupNotifyConfig.objects.get(tenant=self.tenant).is_active)

    def test_admin_of_other_tenant_forbidden(self):
        other = Tenant.objects.create(name="Other", subdomain="other-ct", is_active=True)
        other_admin = User.objects.create_user(username="ct-oadmin2", password="x", full_name="Админ Другой")
        TenantMembership.objects.create(tenant=other, user=other_admin, is_active=True)
        TenantUserRole.objects.create(tenant=other, user=other_admin, role=TenantUserRole.ROLE_ADMIN)
        self.client.force_authenticate(other_admin)
        res = self._put({"is_active": False, "recipient_ids": []})
        self.assertIn(res.status_code, (403, 404))
        self.assertTrue(CardTopupNotifyConfig.objects.get(tenant=self.tenant).is_active)

    def test_non_admin_forbidden(self):
        member = User.objects.create_user(username="ct-requester", password="x", full_name="Рядовой")
        TenantMembership.objects.create(tenant=self.tenant, user=member, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=member, role=TenantUserRole.ROLE_REQUESTER)
        self.client.force_authenticate(member)
        self.assertEqual(self.client.get(URL, HTTP_HOST=self.host).status_code, 403)
        self.assertEqual(self._put({"is_active": False, "recipient_ids": []}).status_code, 403)

    def test_anonymous_rejected(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(URL, HTTP_HOST=self.host).status_code, (401, 403))
