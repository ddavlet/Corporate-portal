"""Shared portal host (PORTAL_SHARED_HOST): company from X-Tenant, checked by membership in DRF auth.

Tests go through the full stack with real JWT (force_authenticate would skip the auth class).
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.test_utils import list_results
from apps.modules.investments.models import InvestPayoutScheduleShareLink
from apps.modules.investments.views import InvestmentApprovalWebhookView
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

SHARED = "app.example.com"
FORBIDDEN_BODY = {"detail": "Нет доступа к компании.", "code": "tenant_forbidden"}
REQUIRED_BODY = {"detail": "Не выбрана компания.", "code": "tenant_required"}


class SharedHostFixtureMixin:
    """acme: active member (admin); beta: inactive membership; gamma: inactive tenant; delta: foreign."""

    def setUp(self):
        self.acme = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.beta = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True)
        self.gamma = Tenant.objects.create(name="Gamma", subdomain="gamma", is_active=False)
        self.delta = Tenant.objects.create(name="Delta", subdomain="delta", is_active=True)
        self.user = User.objects.create_user(username="shared-user", password="x")
        self.outsider = User.objects.create_user(username="shared-outsider", password="x")
        TenantMembership.objects.create(tenant=self.acme, user=self.user, is_active=True)
        TenantMembership.objects.create(tenant=self.beta, user=self.user, is_active=False)
        TenantMembership.objects.create(tenant=self.gamma, user=self.user, is_active=True)
        TenantMembership.objects.create(tenant=self.delta, user=self.outsider, is_active=True)
        for tenant in (self.acme, self.beta, self.delta):
            TenantModuleConfig.objects.create(tenant=tenant, module_key="requests", is_enabled=True)
        TenantUserRole.objects.create(tenant=self.acme, user=self.user, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.beta, user=self.user, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.delta, user=self.outsider, role=TenantUserRole.ROLE_ADMIN)

    def _auth(self, user=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user or self.user).access_token}"}

    def _get(self, path, *, tenant=None, user=None, anonymous=False, host=SHARED):
        headers = {"HTTP_HOST": host}
        if not anonymous:
            headers.update(self._auth(user))
        if tenant is not None:
            headers["HTTP_X_TENANT"] = tenant
        return self.client.get(path, **headers)

    def _request(self, tenant, title):
        return Request.objects.create(
            tenant=tenant, created_by=self.user, title=title, billing_date=timezone.localdate()
        )


@override_settings(BASE_DOMAIN="example.com", PORTAL_SHARED_HOST=SHARED, ALLOWED_HOSTS=["*"])
class SharedHostAuthenticationTests(SharedHostFixtureMixin, APITestCase):
    def test_member_gets_only_selected_company_data(self):  # crit. 2
        own = self._request(self.acme, "acme request")
        foreign = self._request(self.delta, "delta request")

        res = self._get("/api/requests/", tenant="acme")

        self.assertEqual(res.status_code, 200, res.content)
        ids = {row["id"] for row in list_results(res)}
        self.assertIn(own.id, ids)
        self.assertNotIn(foreign.id, ids)

    def test_header_is_case_insensitive(self):
        res = self._get("/api/settings-access/", tenant="ACME")

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["tenant_name"], "Acme")

    def test_same_403_for_foreign_inactive_and_unknown_company(self):  # crit. 3
        for subdomain in ("delta", "gamma", "beta", "nope"):
            with self.subTest(subdomain=subdomain):
                res = self._get("/api/requests/", tenant=subdomain)
                self.assertEqual(res.status_code, 403)
                self.assertEqual(res.json(), FORBIDDEN_BODY)

    def test_without_header_tenant_required(self):  # crit. 4
        res = self._get("/api/requests/")

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json(), REQUIRED_BODY)

    def test_header_without_jwt_is_401(self):  # crit. 5
        res = self._get("/api/requests/", tenant="acme", anonymous=True)

        self.assertEqual(res.status_code, 401)

    def test_token_and_refresh_work_without_header(self):  # crit. 7
        res = self.client.post(
            "/api/auth/token/", {"username": "shared-user", "password": "x"}, format="json", HTTP_HOST=SHARED
        )
        self.assertEqual(res.status_code, 200, res.content)
        refresh = self.client.post(
            "/api/auth/token/refresh/", {"refresh": res.json()["refresh"]}, format="json", HTTP_HOST=SHARED
        )
        self.assertEqual(refresh.status_code, 200, refresh.content)

    def test_tenantless_path_ignores_forbidden_header(self):
        res = self._get("/api/me/companies/", tenant="delta")

        self.assertEqual(res.status_code, 200, res.content)

    def test_admin_path_is_not_served_on_shared_host(self):  # crit. 8
        res = self._get("/api/admin/", tenant="acme")

        self.assertEqual(res.status_code, 404)

    def test_telegram_chats_and_bot_setup_use_header_company(self):
        for path in ("/api/messaging-gateway/chats/", "/api/messaging-gateway/bot-setup/"):
            with self.subTest(path=path):
                self.assertEqual(self._get(path, tenant="acme").status_code, 200)
                self.assertEqual(self._get(path).json(), REQUIRED_BODY)

    def test_telegram_chats_forbidden_for_non_admin(self):
        requester = User.objects.create_user(username="shared-requester", password="x")
        TenantMembership.objects.create(tenant=self.acme, user=requester, is_active=True)
        TenantUserRole.objects.create(tenant=self.acme, user=requester, role=TenantUserRole.ROLE_REQUESTER)

        for path in ("/api/messaging-gateway/chats/", "/api/messaging-gateway/bot-setup/"):
            with self.subTest(path=path):
                self.assertEqual(self._get(path, tenant="acme", user=requester).status_code, 403)

    def test_mcp_token_is_rejected(self):
        from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user

        _, access = mcp_jwt_pair_for_user(self.user, self.acme.id)
        res = self.client.get(
            "/api/requests/", HTTP_HOST=SHARED, HTTP_X_TENANT="acme", HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        self.assertEqual(res.status_code, 401)

    def test_subdomain_ignores_header(self):  # crit. 6 end to end
        res = self._get("/api/settings-access/", tenant="delta", host="acme.example.com")

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["tenant_name"], "Acme")


@override_settings(BASE_DOMAIN="example.com", PORTAL_SHARED_HOST="", ALLOWED_HOSTS=["*"])
class SharedHostDisabledRegressionTests(SharedHostFixtureMixin, APITestCase):  # crit. 1
    def test_subdomain_works_as_before(self):
        own = self._request(self.acme, "acme request")

        res = self._get("/api/requests/", host="acme.example.com")

        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn(own.id, {row["id"] for row in list_results(res)})

    def test_app_host_is_unknown_tenant(self):
        res = self._get("/api/requests/", tenant="acme")

        self.assertEqual(res.status_code, 404)

    def test_portal_config_reports_mode_off(self):
        res = self.client.get("/api/portal/config/", HTTP_HOST="acme.example.com")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"shared_host": None})


@override_settings(BASE_DOMAIN="example.com", PORTAL_SHARED_HOST=SHARED, ALLOWED_HOSTS=["*"])
class MyCompaniesApiTests(SharedHostFixtureMixin, APITestCase):
    URL = "/api/me/companies/"

    def test_lists_active_memberships_in_active_tenants(self):  # crit. 9
        aardvark = Tenant.objects.create(name="Aardvark", subdomain="aardvark", is_active=True)
        TenantMembership.objects.create(tenant=aardvark, user=self.user, is_active=True)

        res = self._get(self.URL)

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(
            res.json(),
            {
                "companies": [
                    {"subdomain": "aardvark", "name": "Aardvark", "action_items_count": 0},
                    {"subdomain": "acme", "name": "Acme", "action_items_count": 0},
                ]
            },
        )

    def test_counts_action_items(self):
        with patch(
            "apps.modules.notifications.services.collect_action_items",
            return_value=[{"id": 1}, {"id": 2}],
        ):
            res = self._get(self.URL)

        self.assertEqual(res.json()["companies"][0]["action_items_count"], 2)

    def test_failing_company_counter_is_zero_and_logged(self):
        aardvark = Tenant.objects.create(name="Aardvark", subdomain="aardvark", is_active=True)
        TenantMembership.objects.create(tenant=aardvark, user=self.user, is_active=True)

        def fake_collect(*, tenant, user):
            if tenant.subdomain == "aardvark":
                raise RuntimeError("boom")
            return [{"id": 1}]

        with patch(
            "apps.modules.notifications.services.collect_action_items", side_effect=fake_collect
        ), self.assertLogs("apps.modules.notifications.services", level="ERROR"):
            res = self._get(self.URL)

        self.assertEqual(res.status_code, 200)
        counts = {c["subdomain"]: c["action_items_count"] for c in res.json()["companies"]}
        self.assertEqual(counts, {"aardvark": 0, "acme": 1})

    def test_counters_failure_keeps_company_list(self):
        with patch(
            "apps.modules.notifications.services.collect_action_items_by_tenant",
            side_effect=RuntimeError("boom"),
        ), self.assertLogs("apps.tenants.views", level="ERROR"):
            res = self._get(self.URL)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["companies"], [{"subdomain": "acme", "name": "Acme", "action_items_count": 0}])

    def test_empty_list_for_user_without_companies(self):
        lonely = User.objects.create_user(username="shared-lonely", password="x")

        res = self._get(self.URL, user=lonely)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"companies": []})

    def test_anonymous_gets_401(self):
        self.assertEqual(self._get(self.URL, anonymous=True).status_code, 401)

    def test_all_action_items_without_header(self):  # crit. 7
        res = self._get("/api/notifications/action-items/all/")

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json(), {"count": 0, "items": []})


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class PortalConfigApiTests(APITestCase):
    URL = "/api/portal/config/"

    @override_settings(PORTAL_SHARED_HOST=SHARED)
    def test_shared_host_is_reported_without_jwt(self):
        res = self.client.get(self.URL, HTTP_HOST=SHARED)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"shared_host": SHARED})

    @override_settings(PORTAL_SHARED_HOST=SHARED)
    def test_invalid_jwt_is_not_checked(self):
        res = self.client.get(self.URL, HTTP_HOST=SHARED, HTTP_AUTHORIZATION="Bearer broken")

        self.assertEqual(res.status_code, 200)


@override_settings(BASE_DOMAIN="example.com", PORTAL_SHARED_HOST=SHARED, ALLOWED_HOSTS=["*"])
class SharedHostAnonymousPathsTests(SharedHostFixtureMixin, APITestCase):
    """AllowAny paths on the shared host (step 17): controlled answers, X-Tenant never applied."""

    def _both(self, method, path, data=None):
        for header in (None, "acme"):
            extra = {"HTTP_HOST": SHARED}
            if header:
                extra["HTTP_X_TENANT"] = header
            if method == "post":
                yield header, self.client.post(path, data or {}, format="json", **extra)
            else:
                yield header, self.client.get(path, **extra)

    @patch("apps.modules.telegram_approvals.views.save_telegram_event")
    def test_events_callback_as_on_host_without_subdomain(self, save_event):
        for header, res in self._both("post", "/api/messaging-gateway/events/", {"event": "x"}):
            with self.subTest(header=header):
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json(), {"ok": True})

    def test_webhook_callback_validates_payload_without_tenant(self):
        for header, res in self._both("post", "/api/messaging-gateway/webhook/"):
            with self.subTest(header=header):
                self.assertEqual(res.status_code, 400, res.content)

    def test_public_payout_schedule_by_token(self):
        link = InvestPayoutScheduleShareLink.objects.create(
            tenant=self.delta, token="shared-host-public-token", created_by=self.outsider
        )
        for header, res in self._both("get", f"/api/investments/public/payout-schedule/{link.token}/"):
            with self.subTest(header=header):
                self.assertEqual(res.status_code, 200, res.content)
                self.assertEqual(res.json()["filters"]["tenant_name"], "Delta")

    def test_public_payout_schedule_unknown_token(self):
        for header, res in self._both("get", "/api/investments/public/payout-schedule/nope/"):
            with self.subTest(header=header):
                self.assertEqual(res.status_code, 404)

    def test_investment_approval_callback_has_no_public_url(self):
        """InvestmentApprovalWebhookView is reached only through the messaging-gateway webhook."""

        def walk(patterns):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    yield from walk(pattern.url_patterns)
                elif isinstance(pattern, URLPattern):
                    yield getattr(pattern.callback, "view_class", None)

        self.assertNotIn(InvestmentApprovalWebhookView, set(walk(get_resolver().url_patterns)))


@override_settings(BASE_DOMAIN="example.com", PORTAL_SHARED_HOST=SHARED, ALLOWED_HOSTS=["*"])
class SharedHostMiddlewareOrderTests(APITestCase):
    """Full stack: on the shared host the n8n middleware resolves by Host only, X-Tenant is ignored."""

    def setUp(self):
        Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

    def test_n8n_prefix_ignores_header(self):
        res = self.client.get("/api/n8n/vendors/", HTTP_HOST=SHARED, HTTP_X_TENANT="acme")

        self.assertIn(res.status_code, (400, 404))
        self.assertEqual(res.json(), {"detail": "Unknown tenant."})

    @override_settings(PORTAL_SHARED_HOST="portal.other.org")
    def test_n8n_prefix_on_shared_host_outside_base_domain_is_unknown_tenant(self):
        # The shared host check in the n8n middleware comes before the Host subdomain parse.
        res = self.client.get("/api/n8n/vendors/", HTTP_HOST="portal.other.org", HTTP_X_TENANT="acme")

        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json(), {"detail": "Unknown tenant."})

    def test_n8n_prefix_never_resolves_reserved_tenant_from_shared_host_name(self):
        # Host app.example.com -> subdomain "app"; a tenant with that slug must not be picked up.
        Tenant.objects.create(name="App", subdomain="app", is_active=True)

        res = self.client.get("/api/n8n/vendors/", HTTP_HOST=SHARED)

        self.assertIn(res.status_code, (400, 404))
        self.assertNotEqual(res.status_code, 200)
