from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

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



@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class JwtRefreshLifetimeTests(APITestCase):
    """Sign-in must survive more than a day: 30-day refresh token renewed on every refresh."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u1", password="pass12345", full_name="User One")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        self.host = "acme.example.com"

    def _obtain(self):
        res = self.client.post(
            "/api/auth/token/",
            {"username": "u1", "password": "pass12345"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        return res.data

    def test_refresh_token_lives_thirty_days(self):
        refresh = RefreshToken(self._obtain()["refresh"])

        lifetime = refresh["exp"] - refresh["iat"]
        self.assertEqual(lifetime, int(timedelta(days=30).total_seconds()))

    def test_refresh_returns_a_new_refresh_token_with_a_fresh_expiry(self):
        first = self._obtain()["refresh"]
        old_exp = RefreshToken(first)["exp"]

        with patch("rest_framework_simplejwt.tokens.aware_utcnow", return_value=timezone.now() + timedelta(days=2)):
            res = self.client.post(
                "/api/auth/token/refresh/", {"refresh": first}, format="json", HTTP_HOST=self.host
            )

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertNotEqual(res.data["refresh"], first)
        # Issued «two days later»: PyJWT checks iat against the real clock, so read it without verification.
        self.assertGreater(RefreshToken(res.data["refresh"], verify=False)["exp"], old_exp)

    def test_refresh_still_works_after_more_than_a_day(self):
        first = self._obtain()["refresh"]

        with patch("rest_framework_simplejwt.tokens.aware_utcnow", return_value=timezone.now() + timedelta(days=3)):
            res = self.client.post(
                "/api/auth/token/refresh/", {"refresh": first}, format="json", HTTP_HOST=self.host
            )

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)

    def _get_companies(self, access):
        return self.client.get("/api/me/companies/", HTTP_HOST=self.host, HTTP_AUTHORIZATION=f"Bearer {access}")

    def test_password_change_revokes_access_and_refresh(self):
        tokens = self._obtain()
        self.assertEqual(self._get_companies(tokens["access"]).status_code, status.HTTP_200_OK)

        self.user.set_password("newpass12345")
        self.user.save(update_fields=["password"])

        self.assertEqual(self._get_companies(tokens["access"]).status_code, status.HTTP_401_UNAUTHORIZED)
        res = self.client.post(
            "/api/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.content)

    def test_refuses_an_mcp_refresh_token(self):
        mcp_refresh = RefreshToken.for_user(self.user)
        mcp_refresh["mcp_tenant_id"] = self.tenant.id

        res = self.client.post(
            "/api/auth/token/refresh/", {"refresh": str(mcp_refresh)}, format="json", HTTP_HOST=self.host
        )

        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.content)
        self.assertNotIn("refresh", res.data)
