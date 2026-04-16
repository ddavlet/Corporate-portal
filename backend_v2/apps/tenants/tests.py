from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.http import Http404
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.middleware import TenantSubdomainMiddleware
from apps.tenants.models import (
    Tenant,
    TenantIntegrationConfig,
    TenantMembership,
    TenantModuleConfig,
    TenantUserPreference,
    TenantUserRole,
)

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
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER)
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
                "portal_feedback_telegram_chat_id": -1001234567890,
                "portal_feedback_telegram_action": "send_portal_feedback",
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
        self.assertEqual(cfg.portal_feedback_telegram_chat_id, -1001234567890)
        self.assertEqual(cfg.portal_feedback_telegram_action, "send_portal_feedback")

        get = self.client.get(self.url, **self._auth_headers(self.admin))
        self.assertEqual(get.status_code, 200, get.content)
        self.assertEqual(get.data["telegram_approvals_bridge_token"], "********")
        self.assertEqual(get.data["requests_file_gateway_token"], "********")
        self.assertIn("telegram_approvals_message_template", get.data)
        self.assertEqual(get.data["portal_feedback_telegram_chat_id"], -1001234567890)
        self.assertEqual(get.data["portal_feedback_telegram_action"], "send_portal_feedback")

    def test_non_admin_forbidden(self):
        res = self.client.get(self.url, **self._auth_headers(self.user))
        self.assertEqual(res.status_code, 403)

    def test_access_matrix_admin_only(self):
        matrix_url = "/api/access-matrix/"

        # Non-admin forbidden
        denied = self.client.get(matrix_url, **self._auth_headers(self.user))
        self.assertEqual(denied.status_code, 403)

        # Admin allowed
        ok = self.client.get(matrix_url, **self._auth_headers(self.admin))
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertIn("modules", ok.data)
        self.assertIn("users", ok.data)
        usernames = {row["username"] for row in ok.data["users"]}
        self.assertIn("admin", usernames)
        self.assertIn("user", usernames)

    def test_settings_access_flags_for_roles(self):
        url = "/api/settings-access/"

        # requester: no settings
        requester_res = self.client.get(url, **self._auth_headers(self.user))
        self.assertEqual(requester_res.status_code, 200, requester_res.content)
        self.assertFalse(requester_res.data["can_open_settings"])
        self.assertFalse(requester_res.data["can_open_admin"])
        self.assertFalse(requester_res.data["can_manage_tenant_settings"])

        director = User.objects.create_user(username="director", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=director, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=director, role=TenantUserRole.ROLE_DIRECTOR)
        director_res = self.client.get(url, **self._auth_headers(director))
        self.assertEqual(director_res.status_code, 200, director_res.content)
        self.assertTrue(director_res.data["can_open_settings"])
        self.assertFalse(director_res.data["can_open_admin"])
        self.assertFalse(director_res.data["can_manage_tenant_settings"])

        admin_res = self.client.get(url, **self._auth_headers(self.admin))
        self.assertEqual(admin_res.status_code, 200, admin_res.content)
        self.assertTrue(admin_res.data["can_open_settings"])
        self.assertTrue(admin_res.data["can_open_admin"])
        self.assertTrue(admin_res.data["can_manage_tenant_settings"])

    def test_investor_gets_only_reports_effective_access(self):
        investor = User.objects.create_user(username="investor", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=investor, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=investor, role=TenantUserRole.ROLE_INVESTOR)
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant, module_key="reports", defaults={"is_enabled": True}
        )
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant, module_key="requests", defaults={"is_enabled": True}
        )

        catalog = self.client.get("/api/modules/", **self._auth_headers(investor))
        self.assertEqual(catalog.status_code, 200, catalog.content)
        by_key = {row["module_key"]: row for row in catalog.data["modules"]}
        self.assertTrue(by_key["reports"]["effective_enabled"])
        self.assertFalse(by_key["requests"]["effective_enabled"])

    def test_investor_cannot_open_admin_or_settings_endpoints(self):
        investor = User.objects.create_user(username="investor2", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=investor, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=investor, role=TenantUserRole.ROLE_INVESTOR)

        settings_res = self.client.get("/api/settings-access/", **self._auth_headers(investor))
        self.assertEqual(settings_res.status_code, 200, settings_res.content)
        self.assertFalse(settings_res.data["can_open_settings"])
        self.assertFalse(settings_res.data["can_open_admin"])

        admin_res = self.client.get("/api/access-matrix/", **self._auth_headers(investor))
        self.assertEqual(admin_res.status_code, 403)

    def test_investor_can_reach_reports_but_not_requests_module(self):
        investor = User.objects.create_user(username="investor3", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=investor, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=investor, role=TenantUserRole.ROLE_INVESTOR)
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant, module_key="reports", defaults={"is_enabled": True}
        )
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant, module_key="requests", defaults={"is_enabled": True}
        )

        reports_res = self.client.get("/api/reports/pnl/", **self._auth_headers(investor))
        self.assertNotEqual(reports_res.status_code, 403)

        requests_res = self.client.get("/api/requests/", **self._auth_headers(investor))
        self.assertEqual(requests_res.status_code, 403)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class UserPreferencesApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.other_tenant = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True)
        self.user = User.objects.create_user(username="prefs_user", password="x")
        self.other_user = User.objects.create_user(username="prefs_other", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.other_user, is_active=True)
        TenantMembership.objects.create(tenant=self.other_tenant, user=self.user, is_active=True)
        self.bulk_url = "/api/user-preferences/"
        self.single_url = "/api/user-preferences/dashboard.widgets.v1/"

    def _auth_headers(self, user, host="acme.example.com"):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": host, "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_upsert_and_isolation_by_tenant_and_user(self):
        put = self.client.put(
            self.single_url,
            {"value": {"pendingApprovals": False, "incomeBreakdown": True}},
            format="json",
            **self._auth_headers(self.user),
        )
        self.assertEqual(put.status_code, 200, put.content)
        self.assertEqual(put.data["key"], "dashboard.widgets.v1")

        row = TenantUserPreference.objects.get(
            tenant=self.tenant,
            user=self.user,
            key="dashboard.widgets.v1",
        )
        self.assertEqual(row.value["pendingApprovals"], False)

        TenantUserPreference.objects.create(
            tenant=self.tenant,
            user=self.other_user,
            key="dashboard.widgets.v1",
            value={"pendingApprovals": True},
        )
        TenantUserPreference.objects.create(
            tenant=self.other_tenant,
            user=self.user,
            key="dashboard.widgets.v1",
            value={"pendingApprovals": True},
        )

        acme_get = self.client.get(
            f"{self.bulk_url}?keys=dashboard.widgets.v1",
            **self._auth_headers(self.user, host="acme.example.com"),
        )
        self.assertEqual(acme_get.status_code, 200, acme_get.content)
        self.assertEqual(len(acme_get.data["items"]), 1)
        self.assertEqual(acme_get.data["items"][0]["value"]["pendingApprovals"], False)

        beta_get = self.client.get(
            f"{self.bulk_url}?keys=dashboard.widgets.v1",
            **self._auth_headers(self.user, host="beta.example.com"),
        )
        self.assertEqual(beta_get.status_code, 200, beta_get.content)
        self.assertEqual(len(beta_get.data["items"]), 1)
        self.assertEqual(beta_get.data["items"][0]["value"]["pendingApprovals"], True)

    def test_forbidden_without_membership(self):
        stranger = User.objects.create_user(username="stranger", password="x")
        denied = self.client.get(
            f"{self.bulk_url}?keys=dashboard.widgets.v1",
            **self._auth_headers(stranger, host="acme.example.com"),
        )
        self.assertEqual(denied.status_code, 403, denied.content)

