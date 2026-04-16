from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class JwtTokenObtainTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u1", password="pass12345", full_name="User One")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        self.host = "acme.example.com"

    def test_obtain_pair_success(self):
        res = self.client.post(
            "/api/auth/token/",
            {"username": "u1", "password": "pass12345"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

