from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ChangePasswordApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u1", password="oldpass12345", full_name="User One")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)

    def _auth(self, user=None):
        u = user or self.user
        token = str(RefreshToken.for_user(u).access_token)
        return {"HTTP_HOST": "acme.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_success_with_correct_old_password(self):
        res = self.client.post(
            "/api/auth/password/change/",
            {"old_password": "oldpass12345", "new_password": "newpass12345"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data.get("detail"), "Пароль обновлён.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newpass12345"))

    def test_rejects_wrong_old_password(self):
        res = self.client.post(
            "/api/auth/password/change/",
            {"old_password": "wrong", "new_password": "newpass12345"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn("текущий", res.data.get("detail", "").lower())

    def test_rejects_missing_old_when_usable_password(self):
        res = self.client.post(
            "/api/auth/password/change/",
            {"new_password": "newpass12345"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)

    def test_success_set_first_password_when_unusable(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        res = self.client.post(
            "/api/auth/password/change/",
            {"new_password": "firstpass12345"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("firstpass12345"))

    def test_rejects_weak_new_password(self):
        res = self.client.post(
            "/api/auth/password/change/",
            {"old_password": "oldpass12345", "new_password": "123"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn("detail", res.data)
