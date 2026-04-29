from unittest.mock import patch

import jwt
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.telegram_oidc import TelegramOidcError, validate_telegram_id_token
from apps.tenants.models import Tenant, TenantIntegrationConfig, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


class ValidateTelegramOidcIdTokenTests(TestCase):
    @patch("apps.accounts.telegram_oidc.requests.get")
    @patch("apps.accounts.telegram_oidc.jwt.decode")
    @patch("apps.accounts.telegram_oidc.jwt.get_unverified_header")
    @patch("apps.accounts.telegram_oidc.jwt.algorithms.RSAAlgorithm.from_jwk")
    def test_invalid_audience_or_issuer_raises(self, m_from_jwk, m_header, m_decode, m_get):
        m_header.return_value = {"kid": "k1"}
        m_get.return_value.json.return_value = {"keys": [{"kid": "k1", "kty": "RSA", "n": "AQAB", "e": "AQAB"}]}
        m_from_jwk.return_value = "public-key"
        m_decode.side_effect = jwt.InvalidAudienceError("bad aud")
        with self.assertRaises(TelegramOidcError):
            validate_telegram_id_token(
                id_token="fake",
                client_id="123",
                jwks_uri="https://oauth.telegram.org/jwks",
                expected_issuer="https://oauth.telegram.org",
            )


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TelegramOidcAuthViewTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user_linked = User.objects.create_user(username="tg_user", password="x")
        self.user_linked.telegram_from_id = 424242
        self.user_linked.save(update_fields=["telegram_from_id"])
        self.user_no_tg = User.objects.create_user(username="plain", password="x")

        for u in (self.user_linked, self.user_no_tg):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user_linked, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user_no_tg, role=TenantUserRole.ROLE_REQUESTER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        cfg.telegram_oidc_client_id = "123456789"
        cfg.set_telegram_oidc_client_secret("secret-oidc")
        cfg.telegram_oidc_redirect_uri = "https://main.kolberg.uz/app/login"
        cfg.save()
        self.host = "acme.example.com"

    @patch("apps.accounts.views_telegram_oidc.get_telegram_oidc_discovery")
    def test_config_endpoint_returns_public_oidc_config(self, m_discovery):
        m_discovery.return_value.authorization_endpoint = "https://oauth.telegram.org/auth"
        res = self.client.get("/api/auth/telegram/oidc/config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["client_id"], "123456789")
        self.assertEqual(res.data["redirect_uri"], "https://main.kolberg.uz/app/login")

    @patch("apps.accounts.views_telegram_oidc.validate_telegram_id_token")
    @patch("apps.accounts.views_telegram_oidc.exchange_code_for_tokens")
    @patch("apps.accounts.views_telegram_oidc.get_telegram_oidc_discovery")
    def test_exchange_returns_jwt_when_user_mapped(self, m_discovery, m_exchange, m_validate):
        m_discovery.return_value.token_endpoint = "https://oauth.telegram.org/token"
        m_discovery.return_value.jwks_uri = "https://oauth.telegram.org/jwks"
        m_discovery.return_value.issuer = "https://oauth.telegram.org"
        m_exchange.return_value = {"id_token": "id-token"}
        m_validate.return_value = {"id": 424242}
        res = self.client.post(
            "/api/auth/telegram/oidc/exchange/",
            {
                "code": "abc",
                "code_verifier": "verifier",
                "redirect_uri": "https://main.kolberg.uz/app/login",
                "nonce": "n1",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

    @patch("apps.accounts.views_telegram_oidc.validate_telegram_id_token")
    @patch("apps.accounts.views_telegram_oidc.exchange_code_for_tokens")
    @patch("apps.accounts.views_telegram_oidc.get_telegram_oidc_discovery")
    def test_403_when_user_not_mapped(self, m_discovery, m_exchange, m_validate):
        m_discovery.return_value.token_endpoint = "https://oauth.telegram.org/token"
        m_discovery.return_value.jwks_uri = "https://oauth.telegram.org/jwks"
        m_discovery.return_value.issuer = "https://oauth.telegram.org"
        m_exchange.return_value = {"id_token": "id-token"}
        m_validate.return_value = {"id": 999999}
        res = self.client.post(
            "/api/auth/telegram/oidc/exchange/",
            {"code": "abc", "code_verifier": "verifier", "redirect_uri": "https://main.kolberg.uz/app/login"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 403)

    @patch("apps.accounts.views_telegram_oidc.validate_telegram_id_token")
    @patch("apps.accounts.views_telegram_oidc.exchange_code_for_tokens")
    @patch("apps.accounts.views_telegram_oidc.get_telegram_oidc_discovery")
    def test_409_when_duplicate_mapping(self, m_discovery, m_exchange, m_validate):
        duplicate = User.objects.create_user(username="dup", password="x")
        duplicate.telegram_from_id = 424242
        duplicate.save(update_fields=["telegram_from_id"])
        TenantMembership.objects.create(tenant=self.tenant, user=duplicate, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=duplicate, role=TenantUserRole.ROLE_REQUESTER)

        m_discovery.return_value.token_endpoint = "https://oauth.telegram.org/token"
        m_discovery.return_value.jwks_uri = "https://oauth.telegram.org/jwks"
        m_discovery.return_value.issuer = "https://oauth.telegram.org"
        m_exchange.return_value = {"id_token": "id-token"}
        m_validate.return_value = {"id": 424242}
        res = self.client.post(
            "/api/auth/telegram/oidc/exchange/",
            {"code": "abc", "code_verifier": "verifier", "redirect_uri": "https://main.kolberg.uz/app/login"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 409)
