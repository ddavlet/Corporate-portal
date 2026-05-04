import os
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.client import RequestFactory
from django.http import Http404
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from config.settings import _allowed_hosts_from_env

from apps.tenants.middleware import RewriteDockerInternalHostMiddleware, TenantSubdomainMiddleware
from apps.tenants.admin import TenantAdminForm
from apps.tenants.models import (
    Tenant,
    TenantIntegrationConfig,
    TenantMembership,
    TenantModuleConfig,
    TenantUserPreference,
    TenantUserRole,
)

User = get_user_model()


class RewriteDockerInternalHostMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_rewrites_legacy_compose_service_hosts(self):
        def get_response(request):
            return request

        mw = RewriteDockerInternalHostMiddleware(get_response)
        for legacy in ("django_v2:8001", "backend_v2:8001"):
            with self.subTest(legacy=legacy):
                req = self.factory.get("/api/messaging-gateway/webhook/", HTTP_HOST=legacy)
                mw(req)
                self.assertEqual(req.META["HTTP_HOST"], "kolberg-django-v2:8001")

    def test_preserves_normal_hosts(self):
        def get_response(request):
            return request

        mw = RewriteDockerInternalHostMiddleware(get_response)
        req = self.factory.get("/api/health/", HTTP_HOST="acme.example.com")
        mw(req)
        self.assertEqual(req.META["HTTP_HOST"], "acme.example.com")


class TenantAdminFormTests(TestCase):
    def test_save_commit_false_persists_tenant_before_module_upserts(self):
        form = TenantAdminForm(
            data={
                "name": "Admin Save Tenant",
                "subdomain": "admin-save-tenant",
                "is_active": "on",
                "telegram_otp_enabled": "",
                "telegram_bot_token": "",
                "telegram_bot_username": "adminsavebot",
                "telegram_oidc_client_id": "",
                "telegram_oidc_client_secret": "",
                "telegram_oidc_redirect_uri": "",
                "enabled_modules": ["requests"],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        tenant = form.save(commit=False)

        self.assertIsNotNone(tenant.pk)
        self.assertTrue(Tenant.objects.filter(pk=tenant.pk).exists())
        self.assertTrue(
            TenantModuleConfig.objects.filter(tenant=tenant, module_key="requests").exists()
        )


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

    def test_skips_tenant_for_messaging_gateway_webhook_on_internal_host(self):
        req = self.factory.post(
            "/api/messaging-gateway/webhook/",
            HTTP_HOST="kolberg_backend_local:8001",
        )

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        res = mw(req)
        self.assertFalse(hasattr(res, "tenant"))

    def test_skips_tenant_for_investment_approval_webhook_on_internal_host(self):
        req = self.factory.post(
            "/api/investments/approvals/webhook/",
            HTTP_HOST="django_v2:8001",
        )

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        res = mw(req)
        self.assertFalse(hasattr(res, "tenant"))


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
                "telegram_bot_username": "@acme_login_bot",
                "telegram_oidc_client_id": "123456789",
                "telegram_oidc_client_secret": "oidc-secret",
                "telegram_oidc_redirect_uri": "https://main.kolberg.uz/app/login",
                "requests_file_gateway_token": "secret-3",
                "messaging_gateway_feedback_recipient_id": -1001234567890,
                "messaging_gateway_feedback_action": "send_portal_feedback",
            },
            format="json",
            **self._auth_headers(self.admin),
        )
        self.assertEqual(put.status_code, 200, put.content)
        self.assertEqual(put.data["telegram_bot_token"], "********")
        self.assertEqual(put.data["requests_file_gateway_token"], "********")

        cfg = TenantIntegrationConfig.objects.get(tenant=self.tenant)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.get_telegram_bot_token(), "bot-secret")
        self.assertEqual(self.tenant.telegram_bot_username, "acme_login_bot")
        self.assertEqual(cfg.telegram_oidc_client_id, "123456789")
        self.assertEqual(cfg.get_telegram_oidc_client_secret(), "oidc-secret")
        self.assertEqual(cfg.telegram_oidc_redirect_uri, "https://main.kolberg.uz/app/login")
        self.assertEqual(cfg.get_requests_file_gateway_token(), "secret-3")
        self.assertEqual(cfg.messaging_gateway_feedback_recipient_id, -1001234567890)
        self.assertEqual(cfg.messaging_gateway_feedback_action, "send_portal_feedback")

        get = self.client.get(self.url, **self._auth_headers(self.admin))
        self.assertEqual(get.status_code, 200, get.content)
        self.assertEqual(get.data["requests_file_gateway_token"], "********")
        self.assertEqual(get.data["telegram_bot_username"], "acme_login_bot")
        self.assertEqual(get.data["telegram_oidc_client_id"], "123456789")
        self.assertEqual(get.data["telegram_oidc_client_secret"], "********")
        self.assertEqual(get.data["telegram_oidc_redirect_uri"], "https://main.kolberg.uz/app/login")
        self.assertEqual(get.data["messaging_gateway_feedback_recipient_id"], -1001234567890)
        self.assertEqual(get.data["messaging_gateway_feedback_action"], "send_portal_feedback")

    def test_non_admin_forbidden(self):
        res = self.client.get(self.url, **self._auth_headers(self.user))
        self.assertEqual(res.status_code, 403)

    @patch("apps.tenants.views.requests.get")
    def test_messaging_webhook_info_gateway_network_error_returns_502(self, mocked_get):
        self.tenant.set_telegram_bot_token("123456:token")
        self.tenant.save(update_fields=["telegram_bot_token_enc"])
        mocked_get.side_effect = requests.RequestException("DNS failure")

        res = self.client.post(
            "/api/tenant-integration-config/messaging-webhook/",
            {"action": "info"},
            format="json",
            **self._auth_headers(self.admin),
        )
        self.assertEqual(res.status_code, 502, res.content)
        self.assertIn("DNS failure", str(res.data.get("detail", "")))

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

    def test_access_matrix_put_requires_admin(self):
        matrix_url = "/api/access-matrix/"
        payload = {
            "assignments": [
                {"user_id": self.user.id, "roles": [TenantUserRole.ROLE_REQUESTER, TenantUserRole.ROLE_APPROVER]},
                {"user_id": self.admin.id, "roles": [TenantUserRole.ROLE_ADMIN]},
            ]
        }
        denied = self.client.put(matrix_url, payload, format="json", **self._auth_headers(self.user))
        self.assertEqual(denied.status_code, 403)

        ok = self.client.put(matrix_url, payload, format="json", **self._auth_headers(self.admin))
        self.assertEqual(ok.status_code, 200, ok.content)
        roles_user = next(row["roles"] for row in ok.data["users"] if row["username"] == "user")
        roles_admin = next(row["roles"] for row in ok.data["users"] if row["username"] == "admin")
        self.assertEqual(sorted(roles_user), sorted(["approver", "requester"]))
        self.assertEqual(roles_admin, ["admin"])

    def test_access_matrix_put_rejects_non_member_user_id(self):
        matrix_url = "/api/access-matrix/"
        outsider = User.objects.create_user(username="outsider", password="x")
        payload = {
            "assignments": [
                {"user_id": self.admin.id, "roles": [TenantUserRole.ROLE_ADMIN]},
                {"user_id": outsider.id, "roles": [TenantUserRole.ROLE_REQUESTER]},
            ]
        }
        res = self.client.put(matrix_url, payload, format="json", **self._auth_headers(self.admin))
        self.assertEqual(res.status_code, 400, res.content)

    def test_access_matrix_put_rejects_removing_last_admin(self):
        matrix_url = "/api/access-matrix/"
        payload = {
            "assignments": [
                {"user_id": self.admin.id, "roles": [TenantUserRole.ROLE_REQUESTER]},
                {"user_id": self.user.id, "roles": [TenantUserRole.ROLE_REQUESTER]},
            ]
        }
        res = self.client.put(matrix_url, payload, format="json", **self._auth_headers(self.admin))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertTrue(
            TenantUserRole.objects.filter(
                tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN
            ).exists()
        )

    def test_settings_access_flags_for_roles(self):
        url = "/api/settings-access/"

        # requester: no settings
        requester_res = self.client.get(url, **self._auth_headers(self.user))
        self.assertEqual(requester_res.status_code, 200, requester_res.content)
        self.assertEqual(requester_res.data["tenant_name"], self.tenant.name)
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
class TenantCashExpenseIdFormatApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="cashfmt", is_active=True)
        self.director = User.objects.create_user(username="cashfmt-dir", password="x")
        self.accountant = User.objects.create_user(username="cashfmt-acc", password="x")
        self.requester = User.objects.create_user(username="cashfmt-req", password="x")
        for u in (self.director, self.accountant, self.requester):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.accountant, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="wallets", is_enabled=True)
        self.url = "/api/tenant/cash-expense-id-format/"
        self.host_hdr = {"HTTP_HOST": "cashfmt.example.com"}

    def _auth(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {**self.host_hdr, "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_director_gets_defaults_and_can_set_pad_without_prefix(self):
        g = self.client.get(self.url, **self._auth(self.director))
        self.assertEqual(g.status_code, 200, g.content)
        self.assertEqual(g.data["cash_expense_external_id_prefix"], "1-")
        self.assertEqual(g.data["cash_expense_external_id_digit_width"], 9)

        p = self.client.put(
            self.url,
            {"cash_expense_external_id_prefix": "", "cash_expense_external_id_digit_width": 11},
            format="json",
            **self._auth(self.director),
        )
        self.assertEqual(p.status_code, 200, p.content)
        self.assertEqual(p.data["cash_expense_external_id_prefix"], "")
        self.assertEqual(p.data["cash_expense_external_id_digit_width"], 11)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.cash_expense_external_id_prefix, "")
        self.assertEqual(self.tenant.cash_expense_external_id_digit_width, 11)

    def test_accountant_can_update(self):
        p = self.client.put(
            self.url,
            {"cash_expense_external_id_prefix": "X-", "cash_expense_external_id_digit_width": 6},
            format="json",
            **self._auth(self.accountant),
        )
        self.assertEqual(p.status_code, 200, p.content)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.cash_expense_external_id_prefix, "X-")
        self.assertEqual(self.tenant.cash_expense_external_id_digit_width, 6)

    def test_requester_forbidden(self):
        r = self.client.get(self.url, **self._auth(self.requester))
        self.assertEqual(r.status_code, 403)


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


class AllowedHostsEnvTests(SimpleTestCase):
    """Internal Docker callbacks; ALLOWED_HOSTS must allow legacy and RFC-valid alias names."""

    def test_empty_env_defaults_to_wildcard(self):
        with patch.dict(os.environ, {"DJANGO_ALLOWED_HOSTS": ""}, clear=False):
            self.assertEqual(_allowed_hosts_from_env(), ["*"])

    def test_wildcard_entry_skips_internal_merge(self):
        with patch.dict(os.environ, {"DJANGO_ALLOWED_HOSTS": "example.com,*"}, clear=False):
            self.assertEqual(_allowed_hosts_from_env(), ["example.com", "*"])

    def test_restricted_list_includes_docker_backend_service_names(self):
        with patch.dict(
            os.environ,
            {"DJANGO_ALLOWED_HOSTS": "neuron.kolberg.uz,main.kolberg.uz"},
            clear=False,
        ):
            got = _allowed_hosts_from_env()
            self.assertEqual(got[:2], ["neuron.kolberg.uz", "main.kolberg.uz"])
            self.assertIn("django_v2", got)
            self.assertIn("backend_v2", got)
            self.assertIn("kolberg-django-v2", got)

