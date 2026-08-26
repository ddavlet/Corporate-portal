from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import Client, TestCase, override_settings

from apps.mcp_server.utils import json_safe, validate_date
from apps.mcp_server.routing import (
    is_mcp_host,
    is_mcp_protocol_path,
    is_well_known_oauth_path,
    mcp_http_enabled,
)


class JsonSafeTests(TestCase):
    def test_datetime_to_isoformat(self):
        result = json_safe({"dt": datetime(2024, 3, 15, 10, 30, 0)})
        self.assertEqual(result["dt"], "2024-03-15T10:30:00")

    def test_date_to_isoformat(self):
        result = json_safe({"d": date(2024, 3, 15)})
        self.assertEqual(result["d"], "2024-03-15")

    def test_decimal_to_str(self):
        result = json_safe({"amount": Decimal("1234.56")})
        self.assertEqual(result["amount"], "1234.56")

    def test_nested_list_of_dicts(self):
        data = [{"dt": datetime(2024, 1, 1), "amount": Decimal("10.00")}]
        result = json_safe(data)
        self.assertEqual(result[0]["dt"], "2024-01-01T00:00:00")
        self.assertEqual(result[0]["amount"], "10.00")

    def test_none_passes_through(self):
        self.assertIsNone(json_safe({"x": None})["x"])

    def test_primitives_pass_through(self):
        data = {"i": 1, "s": "hello", "b": True}
        self.assertEqual(json_safe(data), data)

    def test_datetime_checked_before_date(self):
        # datetime is a subclass of date; must not be serialised as date only
        dt = datetime(2024, 3, 15, 10, 30, 0)
        result = json_safe(dt)
        self.assertIn("T", result)  # isoformat includes time component


class ValidateDateTests(TestCase):
    def test_valid_date_passes(self):
        validate_date("2024-03-15", "date_from")  # no exception

    def test_empty_string_passes(self):
        validate_date("", "date_from")  # no exception

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_date("not-a-date", "date_from")
        self.assertIn("date_from", str(ctx.exception))

    def test_wrong_format_raises(self):
        with self.assertRaises(ValueError):
            validate_date("15/03/2024", "date_to")

    def test_error_message_includes_bad_value(self):
        with self.assertRaises(ValueError) as ctx:
            validate_date("abc", "date_from")
        self.assertIn("abc", str(ctx.exception))


class McpRoutingTests(TestCase):
    def test_fastmcp_paths(self):
        for path in ("/mcp", "/mcp/", "/mcp/authorize", "/mcp/token", "/mcp/register"):
            self.assertTrue(is_mcp_protocol_path(path), path)

    def test_canonical_login_not_fastmcp(self):
        self.assertFalse(is_mcp_protocol_path("/oauth/login/"))

    def test_well_known_not_fastmcp(self):
        for path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource",
        ):
            self.assertFalse(is_mcp_protocol_path(path), path)

    def test_well_known_paths(self):
        self.assertTrue(is_well_known_oauth_path("/.well-known/oauth-authorization-server"))
        self.assertTrue(is_well_known_oauth_path("/.well-known/oauth-protected-resource/"))
        self.assertTrue(is_well_known_oauth_path("/.well-known/oauth-protected-resource/mcp"))
        self.assertTrue(is_well_known_oauth_path("/.well-known/oauth-authorization-server/mcp"))
        self.assertFalse(is_well_known_oauth_path("/mcp/.well-known/oauth-authorization-server"))

    @override_settings(MCP_HTTP_ENABLED=False, MCP_BASE_URL="https://api.kolberg.uz/mcp")
    def test_mcp_host_ignored_when_http_disabled(self):
        self.assertFalse(mcp_http_enabled())
        self.assertFalse(is_mcp_host("api.kolberg.uz"))

    @override_settings(MCP_HTTP_ENABLED=True, MCP_BASE_URL="https://api.kolberg.uz/mcp")
    def test_mcp_host_matches_when_http_enabled(self):
        self.assertTrue(mcp_http_enabled())
        self.assertTrue(is_mcp_host("api.kolberg.uz"))
        self.assertFalse(is_mcp_host("lemonfit.kolberg.uz"))


_MCP_TEST_HOST = "api.kolberg.uz"


@override_settings(
    MCP_HTTP_ENABLED=True,
    MCP_BASE_URL="https://api.kolberg.uz/mcp",
    MCP_RESOURCE_URL="https://api.kolberg.uz/mcp",
    MCP_OAUTH_LOGIN_URL="https://api.kolberg.uz/oauth/login",
    ALLOWED_HOSTS=[_MCP_TEST_HOST, "testserver"],
)
class McpOAuthMetadataTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _mcp_get(self, path: str):
        return self.client.get(path, HTTP_HOST=_MCP_TEST_HOST)

    def test_authorization_server_metadata_points_to_mcp_endpoints(self):
        from apps.mcp_server.oauth.metadata import authorization_server_metadata

        meta = authorization_server_metadata()
        self.assertEqual(meta["issuer"], "https://api.kolberg.uz/mcp")
        self.assertEqual(meta["authorization_endpoint"], "https://api.kolberg.uz/mcp/authorize")
        self.assertEqual(meta["token_endpoint"], "https://api.kolberg.uz/mcp/token")
        self.assertEqual(meta["registration_endpoint"], "https://api.kolberg.uz/mcp/register")
        self.assertIn("S256", meta["code_challenge_methods_supported"])

    def test_protected_resource_metadata(self):
        from apps.mcp_server.oauth.metadata import protected_resource_metadata

        meta = protected_resource_metadata()
        self.assertEqual(meta["resource"], "https://api.kolberg.uz/mcp")
        self.assertEqual(meta["authorization_servers"], ["https://api.kolberg.uz/mcp"])

    def test_protected_resource_metadata_url_has_no_extra_mcp_suffix(self):
        from apps.mcp_server.oauth.metadata import protected_resource_metadata_url

        url = protected_resource_metadata_url()
        self.assertEqual(url, "https://api.kolberg.uz/.well-known/oauth-protected-resource")
        self.assertFalse(url.endswith("/mcp"))

    def test_root_well_known_endpoints_served_by_django(self):
        r = self._mcp_get("/.well-known/oauth-authorization-server")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["authorization_endpoint"], "https://api.kolberg.uz/mcp/authorize")

        r = self._mcp_get("/.well-known/oauth-protected-resource")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["resource"], "https://api.kolberg.uz/mcp")

    def test_oauth_login_page_without_token_returns_400(self):
        r = self._mcp_get("/oauth/login/")
        self.assertEqual(r.status_code, 400)


@override_settings(
    MCP_HTTP_ENABLED=True,
    MCP_BASE_URL="https://api.kolberg.uz/mcp",
    MCP_OAUTH_LOGIN_URL="https://api.kolberg.uz/oauth/login",
    ALLOWED_HOSTS=[_MCP_TEST_HOST, "testserver"],
)
class McpOAuthLoginFlowTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.client = Client()
        get_user_model().objects.create_user(username="alice", password="test-pass")

    def _signed_t(self) -> str:
        from django.core import signing

        return signing.dumps(
            {
                "client_id": "test-client",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "redirect_uri_provided_explicitly": True,
                "code_challenge": "challenge",
                "state": "st",
                "scopes": ["mcp"],
            },
            salt="mcp-oauth-authorize",
        )

    @patch("apps.accounts.otp.send_otp")
    def test_username_post_does_not_500_when_otp_module_present(self, mock_send):
        t = self._signed_t()
        r = self.client.post(
            "/oauth/login/",
            {"t": t, "step": "username", "username": "alice"},
            HTTP_HOST=_MCP_TEST_HOST,
        )
        self.assertEqual(r.status_code, 200, r.content[:500])
        mock_send.assert_called_once()
        self.assertIn(b"otp", r.content.lower())


@override_settings(
    MCP_HTTP_ENABLED=True,
    MCP_BASE_URL="https://api.kolberg.uz/mcp",
    MCP_OAUTH_LOGIN_URL="https://api.kolberg.uz/oauth/login",
    ALLOWED_HOSTS=[_MCP_TEST_HOST, "testserver"],
)
class McpOAuthLongStateTest(TestCase):
    """create_authorization_code must not fail when state exceeds 255 chars."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.mcp_server.oauth.models import OAuthClient

        self.user = get_user_model().objects.create_user(username="n8n_state_test", password="x")
        self.client_obj = OAuthClient.objects.create(
            client_id="n8n-test",
            redirect_uris=["https://dev.kolberg.uz/rest/oauth2-credential/callback"],
            grant_types=["authorization_code"],
            response_types=["code"],
        )

    def test_long_state_does_not_raise(self):
        from apps.mcp_server.oauth.provider import create_authorization_code

        long_state = "x" * 512
        code = create_authorization_code(
            client_id="n8n-test",
            user_id=self.user.id,
            redirect_uri="https://dev.kolberg.uz/rest/oauth2-credential/callback",
            redirect_uri_provided_explicitly=True,
            code_challenge="A" * 43,
            code_challenge_method="S256",
            scopes=["mcp"],
            state=long_state,
        )
        self.assertTrue(len(code) > 10)


class McpInvestmentsBudgetsToolsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant

        User = get_user_model()
        self.user = User.objects.create_user(username="mcp_inv", password="x")
        self.tenant = Tenant.objects.create(name="T", subdomain="invbud", is_active=True, mcp_enabled=True)

    @patch("apps.mcp_server.tools.investments.require_module_access")
    def test_list_invest_companies_scoped(self, mock_access):
        from apps.modules.investments.models import InvestCompany
        from apps.mcp_server.tools import investments as inv_tools

        mock_access.return_value = (None, self.tenant)
        InvestCompany.objects.create(
            tenant=self.tenant, name="HoldCo", created_by=self.user, is_active=True
        )
        rows = inv_tools.list_invest_companies(self.tenant.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "HoldCo")

    @patch("apps.mcp_server.tools.budgets.require_module_access")
    def test_list_budgets_includes_utilization(self, mock_access):
        from apps.modules.budgets.models import Budget
        from apps.modules.requests.models import RequestCategory
        from apps.mcp_server.tools import budgets as bud_tools

        mock_access.return_value = (None, self.tenant)
        cat = RequestCategory.objects.create(tenant=self.tenant, name="Marketing", is_active=True)
        Budget.objects.create(
            tenant=self.tenant,
            name="Q1 Marketing",
            category=cat,
            period_type=Budget.PERIOD_MONTHLY,
            limit_amount="1000.00",
            currency="UZS",
            created_by=self.user,
        )
        rows = bud_tools.list_budgets(self.tenant.id, year=2026, period=1)
        self.assertEqual(len(rows), 1)
        self.assertIn("spent_amount", rows[0])
        self.assertIn("utilization_pct", rows[0])


class McpPnlReportFiltersTests(TestCase):
    """get_pnl_report / get_cashflow_report used to always return every line
    since pnl_config.start_month, unbounded — thousands of rows for tenants
    with a long history. date_from/date_to and aggregate narrow that down
    without touching the shared report builders."""

    def setUp(self):
        from apps.tenants.models import Tenant

        self.tenant = Tenant.objects.create(name="T", subdomain="pnlfilter", is_active=True, mcp_enabled=True)

    @staticmethod
    def _fake_payload():
        return {
            "revenue": [
                {"id": "1", "date": "2026-01-15", "amount": "100", "category": "Sales", "purpose": "p", "description": ""},
                {"id": "2", "date": "2026-02-10", "amount": "50", "category": "Sales", "purpose": "p", "description": ""},
                {"id": "3", "date": "2026-03-05", "amount": "25", "category": "Other", "purpose": "p", "description": ""},
            ],
            "operational_expenses": [],
            "other_expenses": [],
            "invest_returns": [],
            "metadata": {"start_month": "2026-01"},
            "report_settings": {},
        }

    @patch("apps.mcp_server.tools.finance.require_module_access")
    @patch("apps.modules.reports.pnl_builder.build_pnl_payload_from_db")
    def test_date_filter_narrows_rows(self, mock_build, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        mock_build.return_value = self._fake_payload()

        result = fin_tools.get_pnl_report(self.tenant.id, date_from="2026-02-01", date_to="2026-02-28")
        self.assertEqual([r["id"] for r in result["revenue"]], ["2"])

    @patch("apps.mcp_server.tools.finance.require_module_access")
    @patch("apps.modules.reports.pnl_builder.build_pnl_payload_from_db")
    def test_no_filters_returns_everything_unchanged(self, mock_build, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        mock_build.return_value = self._fake_payload()

        result = fin_tools.get_pnl_report(self.tenant.id)
        self.assertEqual(len(result["revenue"]), 3)
        self.assertNotIn("aggregated", result)

    @patch("apps.mcp_server.tools.finance.require_module_access")
    @patch("apps.modules.reports.pnl_builder.build_pnl_payload_from_db")
    def test_aggregate_mode_collapses_to_totals(self, mock_build, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        mock_build.return_value = self._fake_payload()

        result = fin_tools.get_pnl_report(self.tenant.id, aggregate=True)
        self.assertTrue(result["aggregated"])
        self.assertEqual(result["revenue"]["total"], "175")
        self.assertEqual(result["revenue"]["count"], 3)
        self.assertEqual(
            result["revenue"]["by_month"], {"2026-01": "100", "2026-02": "50", "2026-03": "25"}
        )
        self.assertEqual(result["revenue"]["by_category"], {"Other": "25", "Sales": "150"})

    @patch("apps.mcp_server.tools.finance.require_module_access")
    def test_invalid_date_from_raises_value_error(self, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        with self.assertRaises(ValueError):
            fin_tools.get_pnl_report(self.tenant.id, date_from="15/03/2024")

    @patch("apps.mcp_server.tools.finance.require_module_access")
    @patch("apps.modules.reports.cashflow_builder.build_cashflow_payload_from_db")
    def test_cashflow_report_supports_the_same_filters(self, mock_build, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        mock_build.return_value = self._fake_payload()

        result = fin_tools.get_cashflow_report(self.tenant.id, date_from="2026-02-01", date_to="2026-02-28")
        self.assertEqual([r["id"] for r in result["revenue"]], ["2"])


class DjangoMcpToolDecoratorTests(TestCase):
    def test_sync_to_async_wrapper_runs_sync_code(self):
        import asyncio

        from asgiref.sync import sync_to_async

        def sync_add(a: int, b: int) -> int:
            return a + b

        async def run():
            return await sync_to_async(sync_add, thread_sensitive=True)(2, 3)

        self.assertEqual(asyncio.run(run()), 5)


class McpTenantToggleTests(TestCase):
    def _make_tenant(self, *, mcp_enabled):
        t = MagicMock()
        t.id = 1
        t.subdomain = "acme"
        t.mcp_enabled = mcp_enabled
        t.is_active = True
        return t

    def _make_user(self):
        u = MagicMock()
        u.id = 42
        u.is_active = True
        return u

    @patch("apps.mcp_server.auth._get_token", return_value="tok")
    @patch("apps.mcp_server.auth._decode_token", return_value=42)
    @patch("apps.accounts.models.User.objects")
    @patch("apps.tenants.models.Tenant.objects")
    @patch("apps.tenants.models.TenantMembership.objects")
    def test_mcp_disabled_tenant_raises(self, mock_membership, mock_tenant_mgr, mock_user_mgr, _dt, _gt):
        from apps.mcp_server.auth import _get_user_and_tenant

        mock_user_mgr.get.return_value = self._make_user()
        tenant = self._make_tenant(mcp_enabled=False)
        mock_tenant_mgr.get.return_value = tenant

        with self.assertRaises(PermissionError) as ctx:
            _get_user_and_tenant(42, 1)
        self.assertIn("not enabled", str(ctx.exception))

    @patch("apps.mcp_server.auth._get_token", return_value="tok")
    @patch("apps.mcp_server.auth._decode_token", return_value=42)
    @patch("apps.accounts.models.User.objects")
    @patch("apps.tenants.models.Tenant.objects")
    @patch("apps.tenants.models.TenantMembership.objects")
    def test_mcp_enabled_tenant_proceeds(self, mock_membership, mock_tenant_mgr, mock_user_mgr, _dt, _gt):
        from apps.mcp_server.auth import _get_user_and_tenant

        user = self._make_user()
        mock_user_mgr.get.return_value = user
        tenant = self._make_tenant(mcp_enabled=True)
        mock_tenant_mgr.get.return_value = tenant
        mock_membership.filter.return_value.exists.return_value = True

        result_user, result_tenant = _get_user_and_tenant(42, 1)
        self.assertEqual(result_tenant.mcp_enabled, True)


class McpHttpDisabledTests(TestCase):
    """Production default: MCP HTTP/OAuth is parked and must not be served."""

    def setUp(self):
        self.client = Client()

    def test_oauth_login_is_404(self):
        r = self.client.get("/oauth/login/")
        self.assertEqual(r.status_code, 404)

    def test_well_known_authorization_server_is_404(self):
        r = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(r.status_code, 404)

    def test_well_known_protected_resource_is_404(self):
        r = self.client.get("/.well-known/oauth-protected-resource")
        self.assertEqual(r.status_code, 404)


class McpServiceCredentialModelTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="svc-model-test")

    def test_key_prefix_must_be_unique(self):
        from django.db import IntegrityError
        from apps.mcp_server.models import McpServiceCredential

        McpServiceCredential.objects.create(
            key_prefix="dup1", key_hash="x", name="A", service_user=self.user
        )
        other_user = self.user.__class__.objects.create_user(username="svc-model-test-2")
        with self.assertRaises(IntegrityError):
            McpServiceCredential.objects.create(
                key_prefix="dup1", key_hash="x", name="B", service_user=other_user
            )

    def test_str_includes_name_and_prefix(self):
        from apps.mcp_server.models import McpServiceCredential

        cred = McpServiceCredential.objects.create(
            key_prefix="strtest", key_hash="x", name="n8n prod", service_user=self.user
        )
        self.assertIn("n8n prod", str(cred))
        self.assertIn("strtest", str(cred))


class ProvisionServiceCredentialTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant

        self.tenant_a = Tenant.objects.create(name="A", subdomain="svc-a", is_active=True, mcp_enabled=True)
        self.tenant_b = Tenant.objects.create(name="B", subdomain="svc-b", is_active=True, mcp_enabled=True)

    def test_creates_service_user_with_unusable_password(self):
        from apps.mcp_server.services import provision_service_credential

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        self.assertFalse(credential.service_user.has_usable_password())

    def test_raw_key_verifies_and_hash_does_not_match_raw_secret(self):
        from apps.mcp_server.services import provision_service_credential, verify_service_key

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        self.assertNotEqual(credential.key_hash, raw_key)
        found = verify_service_key(raw_key)
        self.assertEqual(found.pk, credential.pk)

    def test_wrong_secret_does_not_verify(self):
        from apps.mcp_server.services import provision_service_credential, verify_service_key

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        prefix = raw_key.split("_")[1]
        self.assertIsNone(verify_service_key(f"svc_{prefix}_wrong-secret"))

    def test_inactive_credential_does_not_verify(self):
        from apps.mcp_server.services import provision_service_credential, verify_service_key

        credential, raw_key = provision_service_credential("n8n", [self.tenant_a.id])
        credential.is_active = False
        credential.save(update_fields=["is_active"])
        self.assertIsNone(verify_service_key(raw_key))

    def test_malformed_key_does_not_verify(self):
        from apps.mcp_server.services import verify_service_key

        self.assertIsNone(verify_service_key("not-a-service-key"))
        self.assertIsNone(verify_service_key("svc_missingsecret"))

    def test_grants_admin_membership_in_scoped_tenants_only(self):
        from apps.mcp_server.services import provision_service_credential
        from apps.tenants.models import TenantMembership, TenantUserRole

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id])
        user = credential.service_user

        self.assertTrue(
            TenantMembership.objects.filter(user=user, tenant=self.tenant_a, is_active=True).exists()
        )
        self.assertTrue(
            TenantUserRole.objects.filter(
                user=user, tenant=self.tenant_a, role=TenantUserRole.ROLE_ADMIN
            ).exists()
        )
        self.assertFalse(TenantMembership.objects.filter(user=user, tenant=self.tenant_b).exists())

    def test_sync_tenant_access_removes_stale_tenants(self):
        from apps.mcp_server.services import provision_service_credential, sync_tenant_access
        from apps.tenants.models import TenantMembership, TenantUserRole

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id, self.tenant_b.id])
        user = credential.service_user

        credential.tenants.remove(self.tenant_b)
        sync_tenant_access(credential)

        self.assertFalse(
            TenantMembership.objects.filter(user=user, tenant=self.tenant_b, is_active=True).exists()
        )
        self.assertFalse(TenantUserRole.objects.filter(user=user, tenant=self.tenant_b).exists())
        # tenant A untouched
        self.assertTrue(
            TenantMembership.objects.filter(user=user, tenant=self.tenant_a, is_active=True).exists()
        )

    def test_sync_tenant_access_adds_newly_scoped_tenants(self):
        from apps.mcp_server.services import provision_service_credential, sync_tenant_access
        from apps.tenants.models import TenantMembership

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id])
        credential.tenants.add(self.tenant_b)
        sync_tenant_access(credential)

        self.assertTrue(
            TenantMembership.objects.filter(
                user=credential.service_user, tenant=self.tenant_b, is_active=True
            ).exists()
        )


class IsServiceClaimTests(TestCase):
    def test_true_for_token_with_svc_claim(self):
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.mcp_server.auth import _is_service_claim

        user = get_user_model().objects.create_user(username="svc-claim-test")
        token = AccessToken.for_user(user)
        token["svc"] = True
        self.assertTrue(_is_service_claim(str(token)))

    def test_false_for_ordinary_token(self):
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.mcp_server.auth import _is_service_claim

        user = get_user_model().objects.create_user(username="svc-claim-test-2")
        token = AccessToken.for_user(user)
        self.assertFalse(_is_service_claim(str(token)))

    def test_false_for_garbage_token(self):
        from apps.mcp_server.auth import _is_service_claim

        self.assertFalse(_is_service_claim("not-a-jwt"))


class ServiceModeUniformDenialTests(TestCase):
    """service_mode=True must give the exact same message for every failure
    reason, so a service key can't distinguish 'wrong tenant' from 'tenant
    doesn't exist'. service_mode=False (the default) must be untouched —
    covered already by McpTenantToggleTests."""

    def _expect_uniform_denial(self, user_id, tenant_id):
        from apps.mcp_server.auth import _get_user_and_tenant

        with self.assertRaises(PermissionError) as ctx:
            _get_user_and_tenant(user_id, tenant_id, service_mode=True)
        self.assertEqual(
            str(ctx.exception), f"Access denied: tenant {tenant_id} is not accessible with this key"
        )

    def test_nonexistent_tenant(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(username="svc-deny-1")
        self._expect_uniform_denial(user.id, 999_999)

    def test_tenant_exists_but_not_a_member(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant

        user = get_user_model().objects.create_user(username="svc-deny-2")
        tenant = Tenant.objects.create(name="X", subdomain="svc-deny-2", is_active=True, mcp_enabled=True)
        self._expect_uniform_denial(user.id, tenant.id)

    def test_tenant_exists_but_mcp_disabled(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant, TenantMembership

        user = get_user_model().objects.create_user(username="svc-deny-3")
        tenant = Tenant.objects.create(name="Y", subdomain="svc-deny-3", is_active=True, mcp_enabled=False)
        TenantMembership.objects.create(user=user, tenant=tenant, is_active=True)
        self._expect_uniform_denial(user.id, tenant.id)

    def test_two_different_denial_reasons_give_identical_message(self):
        """Same tenant_id, two different underlying failure reasons — the
        message must depend only on tenant_id, never on why access failed.
        (Comparing across two *different* tenant_ids would be meaningless:
        the uniform message embeds tenant_id itself, so it necessarily
        differs when the id differs — that is not a leak, the caller
        already knows the id it asked for.)"""
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant
        from apps.mcp_server.auth import _get_user_and_tenant

        user = get_user_model().objects.create_user(username="svc-deny-4")
        tenant = Tenant.objects.create(name="Z", subdomain="svc-deny-4", is_active=True, mcp_enabled=True)

        # reason 1: tenant exists/active/mcp-enabled, but user isn't a member
        with self.assertRaises(PermissionError) as ctx_a:
            _get_user_and_tenant(user.id, tenant.id, service_mode=True)

        # reason 2: same tenant_id, now inactive -> Tenant.DoesNotExist branch
        tenant.is_active = False
        tenant.save(update_fields=["is_active"])
        with self.assertRaises(PermissionError) as ctx_b:
            _get_user_and_tenant(user.id, tenant.id, service_mode=True)

        self.assertEqual(str(ctx_a.exception), str(ctx_b.exception))


class ServiceKeyMiddlewareTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant
        from apps.mcp_server.services import provision_service_credential

        self.tenant = Tenant.objects.create(
            name="MW", subdomain="svc-mw", is_active=True, mcp_enabled=True
        )
        self.credential, self.raw_key = provision_service_credential("mw-test", [self.tenant.id])

    @staticmethod
    def _scope(headers: list[tuple[bytes, bytes]]):
        return {"type": "http", "path": "/", "headers": headers}

    def _run(self, app, headers):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.service_key import with_service_key_auth

        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        wrapped = with_service_key_auth(app)
        async_to_sync(wrapped)(self._scope(headers), receive, send)
        return sent

    def test_no_header_passes_through_unchanged(self):
        seen_scopes = []

        async def downstream(scope, receive, send):
            seen_scopes.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self._run(downstream, headers=[(b"authorization", b"Bearer original")])
        self.assertEqual(seen_scopes[0]["headers"], [(b"authorization", b"Bearer original")])

    def test_valid_key_rewrites_authorization_header(self):
        from apps.mcp_server.auth import _decode_token, _is_service_claim

        seen_scopes = []

        async def downstream(scope, receive, send):
            seen_scopes.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self._run(downstream, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])

        auth_headers = [v for k, v in seen_scopes[0]["headers"] if k == b"authorization"]
        self.assertEqual(len(auth_headers), 1)
        token = auth_headers[0].decode("latin-1").removeprefix("Bearer ")
        self.assertEqual(_decode_token(token), self.credential.service_user_id)
        self.assertTrue(_is_service_claim(token))

    def test_invalid_key_returns_401_and_never_calls_downstream(self):
        downstream_called = []

        async def downstream(scope, receive, send):
            downstream_called.append(True)

        sent = self._run(downstream, headers=[(b"x-service-key", b"svc_bad_bad")])

        self.assertEqual(downstream_called, [])
        self.assertEqual(sent[0]["status"], 401)

    def test_valid_key_updates_last_used_at(self):
        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self.assertIsNone(self.credential.last_used_at)
        self._run(downstream, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])

        self.credential.refresh_from_db()
        self.assertIsNotNone(self.credential.last_used_at)

    def test_non_http_scope_passes_through(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.service_key import with_service_key_auth

        calls = []

        async def downstream(scope, receive, send):
            calls.append(scope["type"])

        wrapped = with_service_key_auth(downstream)
        async_to_sync(wrapped)({"type": "lifespan"}, None, None)
        self.assertEqual(calls, ["lifespan"])


class McpServiceCredentialAdminTests(TestCase):
    def setUp(self):
        from django.contrib.admin.sites import AdminSite
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant
        from apps.mcp_server.admin import McpServiceCredentialAdmin
        from apps.mcp_server.models import McpServiceCredential

        self.tenant_a = Tenant.objects.create(name="AA", subdomain="admin-a", is_active=True, mcp_enabled=True)
        self.tenant_b = Tenant.objects.create(name="BB", subdomain="admin-b", is_active=True, mcp_enabled=True)
        self.admin = McpServiceCredentialAdmin(McpServiceCredential, AdminSite())
        self.staff = get_user_model().objects.create_user(username="staff", is_staff=True)

    def _fake_request(self):
        from django.test import RequestFactory

        request = RequestFactory().post("/admin/mcp_server/mcpservicecredential/add/")
        request.user = self.staff
        request._messages = _DummyMessages()
        return request

    def test_add_provisions_credential_and_messages_raw_key(self):
        from apps.mcp_server.models import McpServiceCredential

        obj = McpServiceCredential(name="n8n", is_active=True)
        form = _FakeForm(cleaned_data={"tenants": [self.tenant_a]})
        request = self._fake_request()

        self.admin.save_model(request, obj, form, change=False)

        self.assertIsNotNone(obj.pk)
        saved = McpServiceCredential.objects.get(pk=obj.pk)
        self.assertEqual(saved.name, "n8n")
        self.assertTrue(any("shown once" in m for m in request._messages.messages))

    def test_save_related_syncs_tenant_access(self):
        from apps.mcp_server.services import provision_service_credential
        from apps.tenants.models import TenantMembership

        credential, _ = provision_service_credential("n8n", [self.tenant_a.id])
        credential.tenants.add(self.tenant_b)

        request = self._fake_request()
        form = _FakeForm(cleaned_data={}, instance=credential)
        self.admin.save_related(request, form, formsets=[], change=True)

        self.assertTrue(
            TenantMembership.objects.filter(
                user=credential.service_user, tenant=self.tenant_b, is_active=True
            ).exists()
        )


class _FakeForm:
    def __init__(self, cleaned_data, instance=None):
        self.cleaned_data = cleaned_data
        self.instance = instance
        self.save_m2m = lambda: None


class _DummyMessages:
    def __init__(self):
        self.messages = []

    def add(self, level, message, extra_tags):
        self.messages.append(message)


class ServiceKeyEndToEndTests(TestCase):
    """Exercises the real seam between service_key.py's minted token and
    auth.py's require_* functions — the same integration FastMCP relies on
    in production, without driving the full streamable-http/JSON-RPC stack."""

    def setUp(self):
        from apps.tenants.models import Tenant, TenantModuleConfig
        from apps.mcp_server.services import provision_service_credential

        self.tenant_a = Tenant.objects.create(name="E2E-A", subdomain="e2e-a", is_active=True, mcp_enabled=True)
        self.tenant_b = Tenant.objects.create(name="E2E-B", subdomain="e2e-b", is_active=True, mcp_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant_a, module_key="requests", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant_b, module_key="requests", is_enabled=True)

        self.credential, self.raw_key = provision_service_credential("e2e", [self.tenant_a.id])

    def _minted_token(self):
        from apps.mcp_server.http.service_key import _mint_service_access_token

        return _mint_service_access_token(self.credential.service_user)

    def test_service_token_grants_module_access_for_scoped_tenant(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        user, tenant = require_module_access(self.tenant_a.id, "requests")
        self.assertEqual(tenant.id, self.tenant_a.id)
        self.assertEqual(user.id, self.credential.service_user_id)

    def test_service_token_grants_admin_only_tools(self):
        from apps.mcp_server.auth import set_request_token, require_admin_access

        set_request_token(self._minted_token())
        user, tenant = require_admin_access(self.tenant_a.id)
        self.assertEqual(tenant.id, self.tenant_a.id)

    def test_service_token_denied_for_out_of_scope_tenant(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        with self.assertRaises(PermissionError) as ctx:
            require_module_access(self.tenant_b.id, "requests")
        self.assertEqual(
            str(ctx.exception),
            f"Access denied: tenant {self.tenant_b.id} is not accessible with this key",
        )

    def test_service_token_denied_identically_for_nonexistent_tenant(self):
        """Same *shape* of denial for an existing-but-out-of-scope tenant and
        a tenant that doesn't exist at all — asserting literal string equality
        would be wrong here (the two calls use different tenant_ids, and the
        uniform message legitimately embeds the id it was asked about; that's
        not a leak, the caller already supplied that id). What must not leak
        is anything BEYOND "this id is inaccessible" — same template, only the
        (caller-supplied) id varies."""
        import re
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        with self.assertRaises(PermissionError) as ctx_out_of_scope:
            require_module_access(self.tenant_b.id, "requests")
        with self.assertRaises(PermissionError) as ctx_nonexistent:
            require_module_access(999_999, "requests")

        pattern = re.compile(r"^Access denied: tenant \d+ is not accessible with this key$")
        self.assertRegex(str(ctx_out_of_scope.exception), pattern)
        self.assertRegex(str(ctx_nonexistent.exception), pattern)

    def test_human_jwt_path_is_completely_unaffected(self):
        """Sanity check: an ordinary human JWT still goes through the original,
        unmodified messages — service_mode branching must be a strict no-op
        for non-service tokens."""
        from django.contrib.auth import get_user_model
        from apps.tenants.models import TenantMembership
        from apps.mcp_server.auth import set_request_token, require_module_access
        from rest_framework_simplejwt.tokens import AccessToken

        human = get_user_model().objects.create_user(username="e2e-human")
        TenantMembership.objects.create(user=human, tenant=self.tenant_a, is_active=True)
        from apps.tenants.models import TenantUserRole

        TenantUserRole.objects.create(tenant=self.tenant_a, user=human, role=TenantUserRole.ROLE_REQUESTER)

        set_request_token(str(AccessToken.for_user(human)))
        user, tenant = require_module_access(self.tenant_a.id, "requests")
        self.assertEqual(user.id, human.id)

        with self.assertRaises(PermissionError) as ctx:
            require_module_access(self.tenant_b.id, "requests")
        # human path keeps the original, non-uniform message
        self.assertEqual(str(ctx.exception), "User is not an active member of this tenant")
