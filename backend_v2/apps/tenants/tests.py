from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.http import Http404
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.middleware import TenantSubdomainMiddleware
from apps.tenants.models import Tenant, TenantIntegrationConfig, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", TENANT_SUBDOMAIN_FALLBACK=True, ALLOWED_HOSTS=["*"])
class TenantSubdomainMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.tenant = Tenant.objects.create(
            name="Acme",
            subdomain="acme",
            is_active=True,
        )

    def test_attaches_tenant_for_known_subdomain(self):
        req = self.factory.get("/api/health/", HTTP_HOST="acme.example.com")

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        res = mw(req)

        self.assertTrue(hasattr(res, "tenant"))
        self.assertEqual(res.tenant.id, self.tenant.id)

    def test_404_for_unknown_subdomain(self):
        req = self.factory.get("/api/health/", HTTP_HOST="unknown.example.com")

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        with self.assertRaises(Http404):
            mw(req)

    def test_404_when_host_has_no_subdomain(self):
        req = self.factory.get("/api/health/", HTTP_HOST="example.com")

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        with self.assertRaises(Http404):
            mw(req)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TenantIntegrationConfigApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.user = User.objects.create_user(username="user", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN, step=1)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER, step=1)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.url = "/api/tenant-integration-config/"

    def _auth_headers(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": "acme.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_admin_can_put_and_get_integration_config(self):
        put = self.client.put(
            self.url,
            {
                "telegram_bot_token": "bot-secret",
                "telegram_approvals_bridge_dispatch_url": "https://acme.example.com/n8n/telegram/dispatch",
                "telegram_approvals_bridge_token": "secret-1",
                "telegram_approvals_message_template": "<b>{header}</b>\nКомпания: {company_payer}",
                "telegram_approvals_header_new_template": "💰 Новая заявка на расход № {request_id}",
                "n8n_integration_token": "secret-2",
                "requests_file_gateway_token": "secret-3",
            },
            format="json",
            **self._auth_headers(self.admin),
        )
        self.assertEqual(put.status_code, 200, put.content)
        self.assertEqual(put.data["telegram_bot_token"], "********")
        self.assertEqual(put.data["telegram_approvals_bridge_token"], "********")
        self.assertEqual(put.data["n8n_integration_token"], "********")

        cfg = TenantIntegrationConfig.objects.get(tenant=self.tenant)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.get_telegram_bot_token(), "bot-secret")
        self.assertEqual(cfg.get_telegram_approvals_bridge_token(), "secret-1")
        self.assertEqual(cfg.telegram_approvals_message_template, "<b>{header}</b>\nКомпания: {company_payer}")
        self.assertEqual(cfg.telegram_approvals_header_new_template, "💰 Новая заявка на расход № {request_id}")
        self.assertEqual(cfg.get_n8n_integration_token(), "secret-2")
        self.assertEqual(cfg.get_requests_file_gateway_token(), "secret-3")

        get = self.client.get(self.url, **self._auth_headers(self.admin))
        self.assertEqual(get.status_code, 200, get.content)
        self.assertEqual(get.data["telegram_approvals_bridge_token"], "********")
        self.assertEqual(get.data["requests_file_gateway_token"], "********")
        self.assertIn("telegram_approvals_message_template", get.data)

    def test_non_admin_forbidden(self):
        res = self.client.get(self.url, **self._auth_headers(self.user))
        self.assertEqual(res.status_code, 403)

