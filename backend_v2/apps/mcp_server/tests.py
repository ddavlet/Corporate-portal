from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import Client, TestCase, override_settings

from apps.mcp_server.utils import json_safe, validate_date
from apps.mcp_server.routing import (
    is_mcp_login_path,
    is_mcp_protocol_path,
    is_tenant_mcp_path,
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
    def test_protocol_paths(self):
        for path in ("/mcp", "/mcp/", "/mcp/authorize", "/mcp/token", "/mcp/register"):
            self.assertTrue(is_mcp_protocol_path(path), path)

    def test_login_path(self):
        self.assertTrue(is_mcp_login_path("/mcp/login/"))
        self.assertTrue(is_mcp_login_path("/mcp/login"))
        self.assertFalse(is_mcp_login_path("/oauth/login/"))

    def test_well_known_paths(self):
        for path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-authorization-server/mcp",
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp/",
        ):
            self.assertTrue(is_well_known_oauth_path(path), path)
        # SDK-relative variants are answered by config/asgi.py too, never by the SDK placeholder.
        for path in (
            "/mcp/.well-known/oauth-authorization-server",
            "/mcp/.well-known/oauth-protected-resource",
            "/mcp/.well-known/oauth-protected-resource/mcp",
        ):
            self.assertTrue(is_well_known_oauth_path(path), path)
        self.assertFalse(is_well_known_oauth_path("/mcp/"))

    def test_tenant_mcp_path_covers_protocol_and_discovery_only(self):
        self.assertTrue(is_tenant_mcp_path("/mcp/"))
        self.assertTrue(is_tenant_mcp_path("/.well-known/oauth-protected-resource"))
        self.assertFalse(is_tenant_mcp_path("/api/requests/"))
        self.assertFalse(is_tenant_mcp_path("/app/"))

    @override_settings(MCP_HTTP_ENABLED=False)
    def test_http_switch(self):
        self.assertFalse(mcp_http_enabled())


@override_settings(BASE_DOMAIN="kolberg.uz", MCP_ALLOWED_ORIGINS=["https://claude.ai"])
class McpTenantContextTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant

        self.tenant = Tenant.objects.create(name="Lemon", subdomain="lemonctx", is_active=True, mcp_enabled=True)

    def test_resolves_enabled_tenant_from_host(self):
        from apps.mcp_server.tenant_context import resolve_mcp_tenant

        t = resolve_mcp_tenant("lemonctx.kolberg.uz")
        self.assertEqual((t.id, t.subdomain, t.name), (self.tenant.id, "lemonctx", "Lemon"))
        self.assertEqual(t.base_url, "https://lemonctx.kolberg.uz/mcp")

    def test_host_case_and_port_are_ignored(self):
        from apps.mcp_server.tenant_context import resolve_mcp_tenant

        self.assertEqual(resolve_mcp_tenant("LemonCtx.Kolberg.uz:443").id, self.tenant.id)

    def test_disabled_inactive_unknown_resolve_to_none(self):
        from apps.mcp_server.tenant_context import resolve_mcp_tenant
        from apps.tenants.models import Tenant

        Tenant.objects.create(name="Off", subdomain="offctx", is_active=True, mcp_enabled=False)
        Tenant.objects.create(name="Gone", subdomain="gonectx", is_active=False, mcp_enabled=True)
        for host in ("offctx.kolberg.uz", "gonectx.kolberg.uz", "nope.kolberg.uz", "api.kolberg.uz", "kolberg.uz"):
            self.assertIsNone(resolve_mcp_tenant(host), host)

    def test_current_tenant_requires_binding(self):
        from apps.mcp_server.tenant_context import (
            McpTenant, current_tenant, reset_current_tenant, set_current_tenant,
        )

        with self.assertRaises(PermissionError):
            current_tenant()
        token = set_current_tenant(McpTenant(id=7, subdomain="x", name="X"))
        try:
            self.assertEqual(current_tenant().id, 7)
        finally:
            reset_current_tenant(token)
        with self.assertRaises(PermissionError):
            current_tenant()

    def test_origin_rules(self):
        from apps.mcp_server.tenant_context import McpTenant, origin_allowed

        t = McpTenant(id=1, subdomain="lemonctx", name="L")
        self.assertTrue(origin_allowed(None, t))
        self.assertTrue(origin_allowed("", t))
        self.assertTrue(origin_allowed("https://claude.ai", t))
        self.assertTrue(origin_allowed("https://lemonctx.kolberg.uz", t))
        self.assertFalse(origin_allowed("https://evil.example", t))
        self.assertFalse(origin_allowed("https://other.kolberg.uz", t))


class McpOAuthLongStateTest(TestCase):
    """create_authorization_code must not fail when state exceeds 255 chars."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.mcp_server.oauth.models import OAuthClient

        from apps.tenants.models import Tenant

        self.user = get_user_model().objects.create_user(username="n8n_state_test", password="x")
        self.tenant = Tenant.objects.create(name="LS", subdomain="longstate", is_active=True, mcp_enabled=True)
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
            tenant_id=self.tenant.id,
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


def _bind_tenant(tenant):
    from apps.mcp_server.tenant_context import McpTenant, set_current_tenant

    return set_current_tenant(McpTenant(id=tenant.id, subdomain=tenant.subdomain, name=tenant.name))


def _mcp_access_token(user, tenant_id):
    from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user

    _, access = mcp_jwt_pair_for_user(user, tenant_id)
    return str(access)


class McpTokenBindingTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant

        self.user = get_user_model().objects.create_user(username="bind-user")
        self.a = Tenant.objects.create(name="A", subdomain="bind-a", is_active=True, mcp_enabled=True)
        self.b = Tenant.objects.create(name="B", subdomain="bind-b", is_active=True, mcp_enabled=True)

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def test_token_for_its_tenant_decodes(self):
        from apps.mcp_server.auth import _decode_token

        _bind_tenant(self.a)
        self.assertEqual(_decode_token(_mcp_access_token(self.user, self.a.id)), self.user.id)

    def test_token_for_other_tenant_rejected(self):
        from apps.mcp_server.auth import _decode_token

        _bind_tenant(self.b)
        with self.assertRaisesRegex(PermissionError, "not valid for this company"):
            _decode_token(_mcp_access_token(self.user, self.a.id))

    def test_portal_token_rejected(self):
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.mcp_server.auth import _decode_token

        _bind_tenant(self.a)
        with self.assertRaisesRegex(PermissionError, "not valid for this company"):
            _decode_token(str(AccessToken.for_user(self.user)))

    def test_no_env_token_fallback(self):
        import os
        from apps.mcp_server.auth import _get_token, set_request_token

        set_request_token("")
        with patch.dict(os.environ, {"KOLBERG_JWT_TOKEN": "x"}):
            with self.assertRaises(PermissionError):
                _get_token()


class PortalRejectsMcpTokenTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="portal-user")

    def test_portal_auth_is_default(self):
        from django.conf import settings

        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
            ("apps.accounts.authentication.PortalJWTAuthentication",),
        )

    def test_mcp_token_rejected_by_portal(self):
        from rest_framework_simplejwt.exceptions import InvalidToken
        from apps.accounts.authentication import PortalJWTAuthentication

        with self.assertRaises(InvalidToken):
            PortalJWTAuthentication().get_validated_token(_mcp_access_token(self.user, 1).encode())

    def test_portal_token_still_accepted(self):
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.accounts.authentication import PortalJWTAuthentication

        token = PortalJWTAuthentication().get_validated_token(str(AccessToken.for_user(self.user)).encode())
        self.assertEqual(int(token["user_id"]), self.user.id)

    def test_n8n_integration_auth_rejects_mcp_token(self):
        from apps.accounts.authentication import RejectMcpTokenMixin
        from apps.modules.n8n_integration.authentication import N8nIntegrationAuthentication

        self.assertTrue(issubclass(N8nIntegrationAuthentication, RejectMcpTokenMixin))


class ServiceKeyMiddlewareTests(TestCase):
    def setUp(self):
        from apps.tenants.models import Tenant
        from apps.mcp_server.services import provision_service_credential

        self.tenant = Tenant.objects.create(name="MW", subdomain="svc-mw", is_active=True, mcp_enabled=True)
        self.other = Tenant.objects.create(name="MW2", subdomain="svc-mw2", is_active=True, mcp_enabled=True)
        self.credential, self.raw_key = provision_service_credential("mw-test", [self.tenant.id])

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def _run(self, app, headers, tenant=None):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.service_key import with_service_key_auth

        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        _bind_tenant(tenant or self.tenant)
        async_to_sync(with_service_key_auth(app))({"type": "http", "path": "/", "headers": headers}, receive, send)
        return sent

    @staticmethod
    async def _ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    def test_no_header_passes_through_unchanged(self):
        seen = []

        async def downstream(scope, receive, send):
            seen.append(scope)
            await self._ok(scope, receive, send)

        self._run(downstream, headers=[(b"authorization", b"Bearer original")])
        self.assertEqual(seen[0]["headers"], [(b"authorization", b"Bearer original")])

    def test_valid_key_for_bound_tenant_mints_tenant_token(self):
        from apps.mcp_server.auth import _decode_token, _is_service_claim

        seen = []

        async def downstream(scope, receive, send):
            seen.append(scope)
            await self._ok(scope, receive, send)

        self._run(downstream, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])
        token = [v for k, v in seen[0]["headers"] if k == b"authorization"][0].decode().removeprefix("Bearer ")
        self.assertEqual(_decode_token(token), self.credential.service_user_id)
        self.assertTrue(_is_service_claim(token))

    def test_key_not_bound_to_host_tenant_gets_same_401_as_invalid_key(self):
        called = []

        async def downstream(scope, receive, send):
            called.append(True)

        unbound = self._run(downstream, [(b"x-service-key", self.raw_key.encode("latin-1"))], tenant=self.other)
        invalid = self._run(downstream, [(b"x-service-key", b"svc_bad_bad")])
        self.assertEqual(called, [])
        self.assertEqual(unbound[0]["status"], 401)
        self.assertEqual(unbound[1]["body"], invalid[1]["body"])

    def test_valid_key_updates_last_used_at(self):
        self._run(self._ok, headers=[(b"x-service-key", self.raw_key.encode("latin-1"))])
        self.credential.refresh_from_db()
        self.assertIsNotNone(self.credential.last_used_at)

    def test_non_http_scope_passes_through(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.service_key import with_service_key_auth

        seen = []

        async def downstream(scope, receive, send):
            seen.append(scope["type"])

        async_to_sync(with_service_key_auth(downstream))({"type": "lifespan"}, None, None)
        self.assertEqual(seen, ["lifespan"])


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
    auth.py's require_* functions — the same integration the MCP app relies on
    in production, without driving the full streamable-http/JSON-RPC stack."""

    def setUp(self):
        from apps.tenants.models import Tenant, TenantModuleConfig
        from apps.mcp_server.services import provision_service_credential

        self.tenant_a = Tenant.objects.create(name="E2E-A", subdomain="e2e-a", is_active=True, mcp_enabled=True)
        self.tenant_b = Tenant.objects.create(name="E2E-B", subdomain="e2e-b", is_active=True, mcp_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant_a, module_key="requests", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant_b, module_key="requests", is_enabled=True)

        self.credential, self.raw_key = provision_service_credential("e2e", [self.tenant_a.id])

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def _minted_token(self):
        from apps.mcp_server.http.service_key import _mint_service_access_token

        return _mint_service_access_token(self.credential.service_user, self.tenant_a.id)

    def test_service_token_grants_module_access_for_scoped_tenant(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        _bind_tenant(self.tenant_a)
        set_request_token(self._minted_token())
        user, tenant = require_module_access(self.tenant_a.id, "requests")
        self.assertEqual(tenant.id, self.tenant_a.id)
        self.assertEqual(user.id, self.credential.service_user_id)

    def test_service_token_grants_admin_only_tools(self):
        from apps.mcp_server.auth import set_request_token, require_admin_access

        _bind_tenant(self.tenant_a)
        set_request_token(self._minted_token())
        user, tenant = require_admin_access(self.tenant_a.id)
        self.assertEqual(tenant.id, self.tenant_a.id)

    def test_service_token_rejected_on_other_tenant_host(self):
        from apps.mcp_server.auth import set_request_token, require_module_access

        set_request_token(self._minted_token())
        _bind_tenant(self.tenant_b)
        with self.assertRaisesRegex(PermissionError, "not valid for this company"):
            require_module_access(self.tenant_b.id, "requests")

    def test_human_mcp_token_works_for_member(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import TenantMembership, TenantUserRole
        from apps.mcp_server.auth import set_request_token, require_module_access

        human = get_user_model().objects.create_user(username="e2e-human")
        TenantMembership.objects.create(user=human, tenant=self.tenant_a, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant_a, user=human, role=TenantUserRole.ROLE_REQUESTER)
        _bind_tenant(self.tenant_a)
        set_request_token(_mcp_access_token(human, self.tenant_a.id))
        user, tenant = require_module_access(self.tenant_a.id, "requests")
        self.assertEqual((user.id, tenant.id), (human.id, self.tenant_a.id))


class McpListRequestsDeletedTests(TestCase):
    """Deleted requests must never reach the AI client: Request.objects is an
    ActiveRequestManager that excludes DELETED, even for an explicit status filter."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.modules.requests.models import Request
        from apps.tenants.models import Tenant

        self.user = get_user_model().objects.create_user(username="mcp_req_deleted", password="x")
        self.tenant = Tenant.objects.create(name="T", subdomain="reqdeleted", is_active=True, mcp_enabled=True)

        def _make(status):
            return Request.objects.create(
                tenant=self.tenant,
                created_by=self.user,
                requester=self.user,
                category="Office",
                amount=Decimal("100"),
                currency="UZS",
                status=status,
                billing_date=date(2026, 1, 15),
            )

        self.live = _make(Request.STATUS_APPROVED)
        self.deleted = _make(Request.STATUS_DELETED)

    @patch("apps.mcp_server.tools.requests.require_module_access")
    def test_deleted_requests_are_not_listed(self, mock_access):
        from apps.mcp_server.tools import requests as req_tools

        mock_access.return_value = (None, self.tenant)
        self.assertEqual([r["id"] for r in req_tools.list_requests(self.tenant.id)], [self.live.id])
        self.assertEqual(req_tools.list_requests(self.tenant.id, status="DELETED"), [])


class McpPayrollToolsTests(TestCase):
    """Payroll tools used to return only id/doc_id/created_at (list) and raw lines
    (detail). They now expose status, kind, period, totals and per-employee progress."""

    def setUp(self):
        from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine
        from apps.tenants.models import Tenant

        self.tenant = Tenant.objects.create(name="T", subdomain="mcppayroll", is_active=True, mcp_enabled=True)
        alice = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        self.doc = PayrollDocument.objects.create(
            tenant=self.tenant,
            doc_id="PR-1",
            status=PayrollDocument.STATUS_ACCEPTED,
            kind=PayrollDocument.KIND_SALARY,
            period_month=date(2026, 8, 1),
            payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL,
        )
        PayrollLine.objects.create(document=self.doc, line_no=1, employee="Alice", employee_fk=alice, item="Salary", sum="400")
        PayrollLine.objects.create(document=self.doc, line_no=2, employee="Alice", employee_fk=alice, item="Bonus", sum="150")
        self.draft = PayrollDocument.objects.create(
            tenant=self.tenant, doc_id="PR-2", status=PayrollDocument.STATUS_DRAFT, kind=PayrollDocument.KIND_ADVANCE
        )

    @patch("apps.mcp_server.tools.finance.require_module_access")
    def test_list_returns_status_kind_period_and_totals(self, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        rows = fin_tools.list_payroll_documents(self.tenant.id, status="accepted")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], self.doc.id)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["kind"], "salary")
        self.assertEqual(row["period_month"], "2026-08-01")
        self.assertEqual(Decimal(row["total_sum"]), Decimal("550"))
        self.assertEqual(Decimal(row["paid_total"]), Decimal("0"))
        self.assertEqual(row["lines_count"], 2)

    @patch("apps.mcp_server.tools.finance.require_module_access")
    def test_list_filters_by_kind_and_period(self, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        self.assertEqual([r["id"] for r in fin_tools.list_payroll_documents(self.tenant.id, kind="advance")], [self.draft.id])
        self.assertEqual(
            [r["id"] for r in fin_tools.list_payroll_documents(self.tenant.id, period_from="2026-08-01", period_to="2026-08-31")],
            [self.doc.id],
        )

    @patch("apps.mcp_server.tools.finance.require_module_access")
    def test_list_rejects_unknown_status(self, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        with self.assertRaisesRegex(ValueError, "Invalid status"):
            fin_tools.list_payroll_documents(self.tenant.id, status="PAYED")

    @patch("apps.mcp_server.tools.finance.require_module_access")
    def test_detail_includes_per_employee_progress(self, mock_access):
        from apps.mcp_server.tools import finance as fin_tools

        mock_access.return_value = (None, self.tenant)
        data = fin_tools.get_payroll_document(self.tenant.id, self.doc.id)
        self.assertEqual(data["status"], "accepted")
        self.assertEqual(Decimal(data["remaining_total"]), Decimal("550"))
        self.assertEqual(len(data["lines"]), 2)
        self.assertEqual(len(data["employees"]), 1)
        employee = data["employees"][0]
        self.assertEqual(employee["full_name"], "Alice")
        self.assertEqual(Decimal(employee["accrued"]), Decimal("550"))
        self.assertEqual(Decimal(employee["paid"]), Decimal("0"))
        self.assertEqual(data["payouts"], [])


class McpTaskErrorLanguageTests(TestCase):
    """Task tools returned Russian error messages while every other tool used English."""

    @patch("apps.mcp_server.tools.tasks.require_module_access")
    def test_missing_task_error_is_english(self, mock_access):
        from django.contrib.auth import get_user_model
        from apps.mcp_server.tools import tasks as task_tools
        from apps.tenants.models import Tenant

        user = get_user_model().objects.create_user(username="mcp_task_err", password="x")
        tenant = Tenant.objects.create(name="T", subdomain="taskerr", is_active=True, mcp_enabled=True)
        mock_access.return_value = (user, tenant)

        with self.assertRaisesRegex(ValueError, r"^Task 999999 not found or not accessible\.$"):
            task_tools.update_task_status(tenant.id, 999_999, "done")

    def test_task_tools_have_no_cyrillic_messages(self):
        import inspect
        import re as _re

        from apps.mcp_server.tools import tasks as task_tools

        self.assertIsNone(_re.search(r"[А-Яа-яЁё]", inspect.getsource(task_tools)))


# ALLOWED_HOSTS: the server's post-deploy run uses the real DJANGO_ALLOWED_HOSTS, where the
# test hosts are unknown and Django would answer DisallowedHost (400) instead of routing.
@override_settings(
    MCP_HTTP_ENABLED=True,
    BASE_DOMAIN="kolberg.uz",
    MCP_ALLOWED_ORIGINS=["https://claude.ai"],
    ALLOWED_HOSTS=[".kolberg.uz"],
)
class McpTenantAsgiTests(TestCase):
    """config.asgi.application on tenant hosts: tenant resolution, discovery, origin, dispatch."""

    def setUp(self):
        from apps.tenants.models import Tenant

        self.tenant = Tenant.objects.create(name="Lemon", subdomain="lemonasgi", is_active=True, mcp_enabled=True)
        Tenant.objects.create(name="Off", subdomain="offasgi", is_active=True, mcp_enabled=False)

    def _call(self, host, path, extra_headers=(), mcp_app=None):
        import json
        from asgiref.sync import async_to_sync
        from config.asgi import application

        from django.core.signals import request_finished, request_started
        from django.db import close_old_connections

        sent = []
        incoming = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive():
            if incoming:
                return incoming.pop(0)
            # Django 5 listens for a disconnect while handling; an immediate one aborts
            # the response, so block until the handler cancels this listener.
            import asyncio

            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
            "root_path": "", "query_string": b"", "scheme": "https",
            "headers": [(b"host", host.encode())] + list(extra_headers),
        }
        # Like django.test.Client: a request through the real ASGI handler must not
        # close the TestCase's DB connection.
        request_started.disconnect(close_old_connections)
        request_finished.disconnect(close_old_connections)
        try:
            if mcp_app is None:
                async_to_sync(application)(scope, receive, send)
            else:
                with patch("apps.mcp_server.http.app.get_mcp_asgi_app", return_value=mcp_app):
                    async_to_sync(application)(scope, receive, send)
        finally:
            request_started.connect(close_old_connections)
            request_finished.connect(close_old_connections)
        status = sent[0]["status"]
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        try:
            return status, json.loads(body)
        except ValueError:
            return status, body

    def test_protected_resource_metadata_is_per_host(self):
        status, body = self._call("lemonasgi.kolberg.uz", "/.well-known/oauth-protected-resource")
        self.assertEqual(status, 200)
        self.assertEqual(body["resource"], "https://lemonasgi.kolberg.uz/mcp")
        self.assertEqual(body["authorization_servers"], ["https://lemonasgi.kolberg.uz/mcp"])

    def test_authorization_server_metadata_is_per_host(self):
        status, body = self._call("lemonasgi.kolberg.uz", "/.well-known/oauth-authorization-server/mcp")
        self.assertEqual(status, 200)
        self.assertEqual(body["issuer"], "https://lemonasgi.kolberg.uz/mcp")
        self.assertEqual(body["authorization_endpoint"], "https://lemonasgi.kolberg.uz/mcp/authorize")
        self.assertEqual(body["token_endpoint"], "https://lemonasgi.kolberg.uz/mcp/token")
        self.assertEqual(body["registration_endpoint"], "https://lemonasgi.kolberg.uz/mcp/register")
        self.assertIn("S256", body["code_challenge_methods_supported"])

    def test_unknown_or_disabled_tenant_is_404(self):
        for host in ("offasgi.kolberg.uz", "nope.kolberg.uz", "api.kolberg.uz"):
            status, _ = self._call(host, "/.well-known/oauth-protected-resource")
            self.assertEqual(status, 404, host)

    def test_foreign_origin_is_403_and_missing_origin_passes(self):
        status, _ = self._call(
            "lemonasgi.kolberg.uz", "/.well-known/oauth-protected-resource",
            extra_headers=[(b"origin", b"https://evil.example")],
        )
        self.assertEqual(status, 403)
        status, _ = self._call("lemonasgi.kolberg.uz", "/.well-known/oauth-protected-resource")
        self.assertEqual(status, 200)

    def test_mcp_path_reaches_app_with_tenant_bound_and_prefix_stripped(self):
        from apps.mcp_server.tenant_context import current_tenant

        seen = {}

        async def fake_mcp(scope, receive, send):
            seen["path"] = scope["path"]
            seen["root_path"] = scope["root_path"]
            seen["tenant_id"] = current_tenant().id
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        status, _ = self._call("lemonasgi.kolberg.uz", "/mcp/token", mcp_app=fake_mcp)
        self.assertEqual(status, 200)
        self.assertEqual(seen, {"path": "/token", "root_path": "/mcp", "tenant_id": self.tenant.id})

    def test_unauthorized_response_points_to_host_metadata(self):
        from apps.mcp_server.http.middleware import with_mcp_resource_metadata

        async def unauthorized(scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        status, _ = self._call("lemonasgi.kolberg.uz", "/mcp/", mcp_app=with_mcp_resource_metadata(unauthorized))
        self.assertEqual(status, 401)

    def test_unauthorized_header_value(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.http.middleware import with_mcp_resource_metadata
        from apps.mcp_server.tenant_context import McpTenant, reset_current_tenant, set_current_tenant

        sent = []

        async def unauthorized(scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})

        async def send(message):
            sent.append(message)

        token = set_current_tenant(McpTenant(id=self.tenant.id, subdomain="lemonasgi", name="Lemon"))
        try:
            async_to_sync(with_mcp_resource_metadata(unauthorized))({"type": "http"}, None, send)
        finally:
            reset_current_tenant(token)
        header = dict(sent[0]["headers"])[b"www-authenticate"].decode()
        self.assertIn('resource_metadata="https://lemonasgi.kolberg.uz/.well-known/oauth-protected-resource"', header)

    def test_real_mcp_app_builds_and_requires_auth(self):
        """Smoke test of the production app (SDK auth wiring, middlewares): an
        unauthenticated call is rejected with the host's discovery hint."""
        from asgiref.sync import async_to_sync
        from django.core.signals import request_finished, request_started
        from django.db import close_old_connections
        from config.asgi import application

        sent = []
        incoming = [{"type": "http.request", "body": b"{}", "more_body": False}]

        async def receive():
            if incoming:
                return incoming.pop(0)
            import asyncio

            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http", "method": "POST", "path": "/mcp/", "raw_path": b"/mcp/",
            "root_path": "", "query_string": b"", "scheme": "https",
            "headers": [
                (b"host", b"lemonasgi.kolberg.uz"),
                (b"content-type", b"application/json"),
                (b"accept", b"application/json, text/event-stream"),
            ],
        }
        request_started.disconnect(close_old_connections)
        request_finished.disconnect(close_old_connections)
        try:
            async_to_sync(application)(scope, receive, send)
        finally:
            request_started.connect(close_old_connections)
            request_finished.connect(close_old_connections)
        self.assertEqual(sent[0]["status"], 401)
        header = dict(sent[0]["headers"])[b"www-authenticate"].decode()
        self.assertIn("https://lemonasgi.kolberg.uz/.well-known/oauth-protected-resource", header)

    def test_sdk_relative_discovery_paths_point_to_host(self):
        status, body = self._call("lemonasgi.kolberg.uz", "/mcp/.well-known/oauth-authorization-server")
        self.assertEqual(status, 200)
        self.assertEqual(body["issuer"], "https://lemonasgi.kolberg.uz/mcp")
        status, body = self._call("lemonasgi.kolberg.uz", "/mcp/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(status, 200)
        self.assertEqual(body["resource"], "https://lemonasgi.kolberg.uz/mcp")

    def test_sdk_placeholder_issuer_is_not_a_real_host(self):
        from apps.mcp_server.http.app import get_mcp_asgi_app
        from apps.mcp_server.server import mcp

        get_mcp_asgi_app()
        self.assertTrue(str(mcp.settings.auth.issuer_url).startswith("https://mcp-placeholder.invalid"))

    def test_non_mcp_paths_go_to_django(self):
        status, _ = self._call("lemonasgi.kolberg.uz", "/api/definitely-not-a-route/")
        self.assertEqual(status, 404)


@override_settings(MCP_HTTP_ENABLED=True, BASE_DOMAIN="kolberg.uz")
class McpOAuthProviderTenantTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.mcp_server.oauth.models import OAuthClient
        from apps.tenants.models import Tenant

        self.user = get_user_model().objects.create_user(username="prov-user")
        self.a = Tenant.objects.create(name="A", subdomain="prov-a", is_active=True, mcp_enabled=True)
        self.b = Tenant.objects.create(name="B", subdomain="prov-b", is_active=True, mcp_enabled=True)
        OAuthClient.objects.create(
            client_id="c1", redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
            grant_types=["authorization_code", "refresh_token"], response_types=["code"],
        )

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def _client(self):
        from mcp.shared.auth import OAuthClientInformationFull

        return OAuthClientInformationFull(client_id="c1", redirect_uris=["https://claude.ai/api/mcp/auth_callback"])

    def _params(self, resource=None):
        from mcp.server.auth.provider import AuthorizationParams

        return AuthorizationParams(
            state="st", scopes=["mcp"], code_challenge="A" * 43,
            redirect_uri="https://claude.ai/api/mcp/auth_callback",
            redirect_uri_provided_explicitly=True, resource=resource,
        )

    def _code_for(self, tenant):
        from apps.mcp_server.oauth.provider import create_authorization_code

        return create_authorization_code(
            client_id="c1", user_id=self.user.id, tenant_id=tenant.id,
            redirect_uri="https://claude.ai/api/mcp/auth_callback", redirect_uri_provided_explicitly=True,
            code_challenge="A" * 43, code_challenge_method="S256", scopes=["mcp"], state="st",
        )

    def test_authorize_redirects_to_tenant_login_with_tenant_in_params(self):
        from asgiref.sync import async_to_sync
        from django.core import signing
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        url = async_to_sync(KolbergOAuthProvider().authorize)(self._client(), self._params())
        self.assertTrue(url.startswith("https://prov-a.kolberg.uz/mcp/login/?t="), url)
        params = signing.loads(url.split("t=", 1)[1], salt="mcp-oauth-authorize")
        self.assertEqual(params["tenant_id"], self.a.id)

    def test_authorize_rejects_foreign_resource(self):
        from asgiref.sync import async_to_sync
        from mcp.server.auth.provider import AuthorizeError
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        with self.assertRaises(AuthorizeError):
            async_to_sync(KolbergOAuthProvider().authorize)(self._client(), self._params("https://prov-b.kolberg.uz/mcp"))

    def test_authorize_accepts_resource_with_trailing_slash(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        url = async_to_sync(KolbergOAuthProvider().authorize)(self._client(), self._params("https://prov-a.kolberg.uz/mcp/"))
        self.assertIn("/mcp/login/", url)

    def test_code_of_tenant_a_not_loadable_on_host_b(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        code = self._code_for(self.a)
        _bind_tenant(self.b)
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_authorization_code)(self._client(), code))

    def test_exchange_issues_tenant_bound_tokens(self):
        from asgiref.sync import async_to_sync
        from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        provider = KolbergOAuthProvider()
        code = self._code_for(self.a)
        _bind_tenant(self.a)
        loaded = async_to_sync(provider.load_authorization_code)(self._client(), code)
        token = async_to_sync(provider.exchange_authorization_code)(self._client(), loaded)
        self.assertEqual(AccessToken(token.access_token)["mcp_tenant_id"], self.a.id)
        self.assertEqual(RefreshToken(token.refresh_token)["mcp_tenant_id"], self.a.id)

    def test_refresh_of_tenant_a_rejected_on_host_b(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider
        from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user

        refresh, _ = mcp_jwt_pair_for_user(self.user, self.a.id)
        _bind_tenant(self.b)
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_refresh_token)(self._client(), str(refresh)))

    def test_refresh_without_claim_rejected(self):
        from asgiref.sync import async_to_sync
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        _bind_tenant(self.a)
        legacy = str(RefreshToken.for_user(self.user))
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_refresh_token)(self._client(), legacy))

    def test_refresh_rejected_for_deactivated_user(self):
        from asgiref.sync import async_to_sync
        from mcp.server.auth.provider import TokenError
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider
        from apps.mcp_server.oauth.tokens import mcp_jwt_pair_for_user

        provider = KolbergOAuthProvider()
        refresh, _ = mcp_jwt_pair_for_user(self.user, self.a.id)
        _bind_tenant(self.a)
        loaded = async_to_sync(provider.load_refresh_token)(self._client(), str(refresh))
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(TokenError):
            async_to_sync(provider.exchange_refresh_token)(self._client(), loaded, ["mcp"])

    def test_code_exchange_rejected_for_deactivated_user(self):
        from asgiref.sync import async_to_sync
        from mcp.server.auth.provider import TokenError
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        provider = KolbergOAuthProvider()
        code = self._code_for(self.a)
        _bind_tenant(self.a)
        loaded = async_to_sync(provider.load_authorization_code)(self._client(), code)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(TokenError):
            async_to_sync(provider.exchange_authorization_code)(self._client(), loaded)

    def test_access_token_of_other_tenant_not_loaded(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.oauth.provider import KolbergOAuthProvider

        token = _mcp_access_token(self.user, self.a.id)
        _bind_tenant(self.b)
        self.assertIsNone(async_to_sync(KolbergOAuthProvider().load_access_token)(token))


@override_settings(MCP_HTTP_ENABLED=True, BASE_DOMAIN="kolberg.uz", ALLOWED_HOSTS=["login-a.kolberg.uz", "login-b.kolberg.uz"])
class McpTenantLoginViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.mcp_server.oauth.models import OAuthClient
        from apps.tenants.models import Tenant, TenantMembership

        self.a = Tenant.objects.create(name="A", subdomain="login-a", is_active=True, mcp_enabled=True)
        self.b = Tenant.objects.create(name="B", subdomain="login-b", is_active=True, mcp_enabled=True)
        self.alice = get_user_model().objects.create_user(username="alice", password="x")
        TenantMembership.objects.create(user=self.alice, tenant=self.a, is_active=True)
        OAuthClient.objects.create(client_id="c1", redirect_uris=["https://claude.ai/cb"])

    def _t(self, tenant_id):
        from django.core import signing

        return signing.dumps(
            {"client_id": "c1", "redirect_uri": "https://claude.ai/cb", "redirect_uri_provided_explicitly": True,
             "code_challenge": "A" * 43, "state": "st", "scopes": ["mcp"], "tenant_id": tenant_id},
            salt="mcp-oauth-authorize",
        )

    def test_old_login_url_is_gone(self):
        self.assertEqual(self.client.get("/oauth/login/", HTTP_HOST="login-a.kolberg.uz").status_code, 404)

    def test_login_page_renders_on_tenant_host(self):
        r = self.client.get(f"/mcp/login/?t={self._t(self.a.id)}", HTTP_HOST="login-a.kolberg.uz")
        self.assertEqual(r.status_code, 200)

    def test_params_for_other_tenant_rejected(self):
        r = self.client.get(f"/mcp/login/?t={self._t(self.b.id)}", HTTP_HOST="login-a.kolberg.uz")
        self.assertEqual(r.status_code, 400)

    @patch("apps.accounts.otp.send_otp")
    def test_username_step_sends_otp_via_tenant(self, mock_send):
        r = self.client.post(
            "/mcp/login/", {"t": self._t(self.a.id), "step": "username", "username": "alice"},
            HTTP_HOST="login-a.kolberg.uz",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(mock_send.call_args.kwargs["tenant"].id, self.a.id)

    @patch("apps.accounts.otp.send_otp")
    def test_non_member_cannot_log_in(self, mock_send):
        r = self.client.post(
            "/mcp/login/", {"t": self._t(self.b.id), "step": "username", "username": "alice"},
            HTTP_HOST="login-b.kolberg.uz",
        )
        self.assertContains(r, "Нет доступа к этой компании")
        mock_send.assert_not_called()

    @patch("apps.accounts.otp.verify_otp")
    def test_otp_step_creates_code_bound_to_tenant(self, mock_verify):
        from apps.mcp_server.oauth.models import OAuthAuthorizationCode

        r = self.client.post(
            "/mcp/login/", {"t": self._t(self.a.id), "step": "otp", "username": "alice", "otp": "123456"},
            HTTP_HOST="login-a.kolberg.uz",
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(mock_verify.call_args.kwargs["tenant"].id, self.a.id)
        self.assertEqual(OAuthAuthorizationCode.objects.get().tenant_id, self.a.id)


EXPECTED_TOOL_ACCESS = {
    "get_current_tenant": ("always", None, False),
    "get_my_role": ("always", None, False),
    "list_my_modules": ("always", None, False),
    "list_requests": ("module", "requests", False),
    "get_request": ("module", "requests", False),
    "list_request_categories": ("module", "requests", False),
    "list_cash_expenses": ("module", "cash", False),
    "list_cash_revenues": ("module", "cash", False),
    "list_bank_expenses": ("module", "bank", False),
    "list_bank_revenues": ("module", "bank", False),
    "list_card_expenses": ("module", "corporate_card", False),
    "list_card_revenues": ("module", "corporate_card", False),
    "get_pnl_report": ("module", "reports", False),
    "get_cashflow_report": ("module", "reports", False),
    "list_payroll_documents": ("module", "payroll", False),
    "get_payroll_document": ("module", "payroll", False),
    "get_investment_form_config": ("module", "investments", False),
    "list_invest_companies": ("module", "investments", False),
    "list_invest_returns": ("module", "investments", False),
    "list_project_investments": ("module", "investments", False),
    "list_invest_payout_schedule": ("module", "investments", False),
    "list_budgets": ("module", "budgets", False),
    "get_budget": ("module", "budgets", False),
    "list_budget_spend_requests": ("module", "budgets", False),
    "list_my_tasks": ("module", "tasks", False),
    "get_task": ("module", "tasks", False),
    "update_task_status": ("module", "tasks", False),
    "add_task_comment": ("module", "tasks", False),
    "edit_task": ("module", "tasks", False),
    "delete_task": ("module", "tasks", False),
    "list_assignee_candidates": ("module", "tasks", False),
    "create_task": ("module", "tasks", True),
    "list_vendors": ("module", "vendors", False),
    "list_wallets": ("module", "wallets", False),
    "list_active_users": ("admin_or_director", None, False),
    "get_tenant_info": ("admin_or_director", None, False),
    "list_module_configs": ("admin_or_director", None, False),
    "list_user_roles": ("admin", None, False),
    "list_memberships": ("admin", None, False),
}


class McpToolAccessRegistryTests(TestCase):
    """The access map is what list_tools filters by; it must match the spec table
    and the module each tools/*.py function checks with require_module_access."""

    def test_registry_matches_spec_table(self):
        from apps.mcp_server import server  # noqa: F401 — registers tools
        from apps.mcp_server.django_tools import TOOL_ACCESS

        actual = {n: (a.kind, a.module_key, a.require_admin_or_director) for n, a in TOOL_ACCESS.items()}
        self.assertEqual(actual, EXPECTED_TOOL_ACCESS)

    def test_no_tool_exposes_tenant_id_or_stale_text(self):
        from apps.mcp_server.server import mcp

        tools = mcp._tool_manager.list_tools()
        self.assertEqual(len(tools), len(EXPECTED_TOOL_ACCESS))
        for info in tools:
            with self.subTest(tool=info.name):
                self.assertNotIn("tenant_id", info.parameters.get("properties", {}))
                for stale in ("tenant_id", "list_my_tenants", "Required roles"):
                    self.assertNotIn(stale, info.description or "")


class DjangoMcpToolDecoratorTenantTests(TestCase):
    def test_tenant_id_is_hidden_and_injected(self):
        from asgiref.sync import async_to_sync
        from mcp.server.mcpserver import MCPServer
        from apps.mcp_server.access import Access
        from apps.mcp_server.django_tools import django_mcp_tool
        from apps.mcp_server.tenant_context import McpTenant, reset_current_tenant, set_current_tenant

        test_mcp = MCPServer(name="t")
        tool = django_mcp_tool(test_mcp)

        @tool(access=Access.always())
        def echo_tenant(tenant_id: int, word: str = "x") -> dict:
            """Echo."""
            return {"tenant_id": tenant_id, "word": word}

        from apps.mcp_server.django_tools import TOOL_ACCESS

        try:
            info = test_mcp._tool_manager.list_tools()[0]
            self.assertEqual(set(info.parameters["properties"]), {"word"})

            token = set_current_tenant(McpTenant(id=42, subdomain="s", name="S"))
            try:
                result = async_to_sync(test_mcp.call_tool)("echo_tenant", {"word": "hi"})
            finally:
                reset_current_tenant(token)
        finally:
            TOOL_ACCESS.pop("echo_tenant", None)  # keep the global registry equal to the spec table
        text = "".join(getattr(c, "text", "") for c in result.content)
        self.assertIn("42", text)
        self.assertIn("hi", text)


class McpToolFilteringTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig

        self.tenant = Tenant.objects.create(name="F", subdomain="filt", is_active=True, mcp_enabled=True)
        for key in ("requests", "vendors", "tasks", "cash", "reports", "investments", "payroll"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)
        self.User = get_user_model()
        self.Membership = TenantMembership

    def tearDown(self):
        from apps.mcp_server.tenant_context import set_current_tenant

        set_current_tenant(None)

    def _user_with(self, *roles, member=True):
        from apps.tenants.models import TenantUserRole

        user = self.User.objects.create_user(username=f"u-{'-'.join(roles) or 'none'}-{member}")
        if member:
            self.Membership.objects.create(user=user, tenant=self.tenant, is_active=True)
        for role in roles:
            TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def _visible(self, user):
        from apps.mcp_server.access import visible_tools
        from apps.mcp_server.django_tools import TOOL_ACCESS
        from apps.mcp_server import server  # noqa: F401

        return visible_tools(TOOL_ACCESS, user_id=user.id, tenant_id=self.tenant.id)

    def test_requester_sees_requests_vendors_tasks_only(self):
        v = self._visible(self._user_with("requester"))
        self.assertIn("list_requests", v)
        self.assertIn("list_vendors", v)
        self.assertIn("list_my_tasks", v)
        self.assertNotIn("create_task", v)
        self.assertNotIn("list_cash_expenses", v)
        self.assertNotIn("get_pnl_report", v)
        self.assertNotIn("list_user_roles", v)

    def test_investor_sees_investments_and_reports(self):
        v = self._visible(self._user_with("investor"))
        self.assertIn("list_invest_returns", v)
        self.assertIn("get_pnl_report", v)
        self.assertNotIn("list_requests", v)
        self.assertNotIn("list_my_tasks", v)

    def test_disabled_module_hides_tools_even_for_admin(self):
        v = self._visible(self._user_with("admin"))
        self.assertIn("list_user_roles", v)
        self.assertIn("create_task", v)
        self.assertNotIn("list_budgets", v)  # budgets not enabled
        self.assertNotIn("list_bank_expenses", v)  # bank not enabled

    def test_deactivated_user_sees_nothing(self):
        user = self._user_with("admin")
        user.is_active = False
        user.save(update_fields=["is_active"])
        self.assertEqual(self._visible(user), set())

    def test_non_member_sees_nothing(self):
        self.assertEqual(self._visible(self._user_with("admin", member=False)), set())

    def test_hidden_tool_call_is_unknown_tool(self):
        from asgiref.sync import async_to_sync
        from mcp.server.mcpserver.exceptions import ToolError
        from apps.mcp_server.auth import set_request_token
        from apps.mcp_server.server import mcp

        user = self._user_with("requester")
        _bind_tenant(self.tenant)
        set_request_token(_mcp_access_token(user, self.tenant.id))
        with self.assertRaisesRegex(ToolError, "^Unknown tool: list_payroll_documents$"):
            async_to_sync(mcp.call_tool)("list_payroll_documents", {})

    def test_list_tools_is_filtered(self):
        from asgiref.sync import async_to_sync
        from apps.mcp_server.auth import set_request_token
        from apps.mcp_server.server import mcp

        user = self._user_with("requester")
        _bind_tenant(self.tenant)
        set_request_token(_mcp_access_token(user, self.tenant.id))
        names = {t.name for t in async_to_sync(mcp.list_tools)()}
        self.assertIn("get_current_tenant", names)
        self.assertIn("list_requests", names)
        self.assertNotIn("list_payroll_documents", names)


class McpDeploymentConfigTests(TestCase):
    def test_static_mcp_urls_removed_from_settings(self):
        from django.conf import settings

        for name in ("MCP_BASE_URL", "MCP_RESOURCE_URL", "MCP_OAUTH_LOGIN_URL"):
            self.assertFalse(hasattr(settings, name), name)

    def test_default_allowed_origins_cover_claude_and_chatgpt(self):
        from django.conf import settings

        for origin in ("https://claude.ai", "https://claude.com", "https://chatgpt.com"):
            self.assertIn(origin, settings.MCP_ALLOWED_ORIGINS)

    def test_stdio_entry_point_removed(self):
        from django.core.management import get_commands

        self.assertNotIn("run_mcp_server", get_commands())

    def test_traefik_routes_mcp_on_tenant_hosts_only(self):
        from pathlib import Path

        compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"
        if not compose.exists():
            self.skipTest("docker-compose.yml not available (backend_v2-only checkout)")
        text = compose.read_text()
        self.assertIn("traefik.http.routers.django-v2-tenant-mcp.rule=(${TRAEFIK_BACKEND_V2_HOST_RULE})", text)
        self.assertNotIn("routers.django-v2-mcp.", text)
        self.assertNotIn("MCP_BASE_URL", text)


_E2E_REDIRECT = "https://claude.ai/api/mcp/auth_callback"


class _AsgiResponse:
    def __init__(self, status_code, headers, body):
        self.status_code = status_code
        self.headers = headers
        self.text = body.decode("utf-8", "replace")

    def json(self):
        import json

        return json.loads(self.text)


async def _asgi_request(app, host, method, path, *, params=None, headers=None, json_body=None, form=None):
    """Minimal ASGI client (no httpx in the project): one request, buffered response."""
    import asyncio
    import json
    from urllib.parse import urlencode

    hdrs = {"host": host, **{k.lower(): v for k, v in (headers or {}).items()}}
    body = b""
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs.setdefault("content-type", "application/json")
    elif form is not None:
        body = urlencode(form).encode()
        hdrs["content-type"] = "application/x-www-form-urlencoded"
    if body:
        hdrs["content-length"] = str(len(body))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "https", "path": path, "raw_path": path.encode(), "root_path": "",
        "query_string": urlencode(params or {}).encode(),
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in hdrs.items()],
        "client": ("127.0.0.1", 12345), "server": (host, 443),
    }
    incoming = [{"type": "http.request", "body": body, "more_body": False}]
    done = asyncio.Event()
    status = {"code": None, "headers": {}}
    chunks = []

    async def receive():
        if incoming:
            return incoming.pop(0)
        await done.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]
            status["headers"] = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                done.set()

    await app(scope, receive, send)
    done.set()
    return _AsgiResponse(status["code"], status["headers"], b"".join(chunks))


def _rpc_payload(response):
    """JSON-RPC message from a streamable-HTTP response (JSON or a one-event SSE stream)."""
    import json

    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError(f"no SSE data line in: {response.text[:300]}")
    return response.json()


@override_settings(MCP_HTTP_ENABLED=True, BASE_DOMAIN="kolberg.uz", MCP_ALLOWED_ORIGINS=["https://claude.ai"])
class McpEndToEndOAuthFlowTests(TestCase):
    """The whole connector path through the real SDK app with its lifespan running:
    register → authorize (RFC 8707 resource) → token → tools/list (filtered) →
    tools/call of a visible and of a hidden tool, all on a tenant host."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

        self.tenant = Tenant.objects.create(name="Flow", subdomain="e2eflow", is_active=True, mcp_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
        self.user = get_user_model().objects.create_user(username="e2e-flow-user")
        TenantMembership.objects.create(user=self.user, tenant=self.tenant, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER)

    def test_full_connector_flow_on_tenant_host(self):
        from asgiref.sync import async_to_sync
        from django.core.signals import request_finished, request_started
        from django.db import close_old_connections

        request_started.disconnect(close_old_connections)
        request_finished.disconnect(close_old_connections)
        try:
            async_to_sync(self._flow)()
        finally:
            request_started.connect(close_old_connections)
            request_finished.connect(close_old_connections)

    async def _flow(self):
        import asyncio
        import base64
        import hashlib
        import secrets

        from asgiref.sync import sync_to_async

        from apps.mcp_server.oauth.provider import create_authorization_code
        from config.asgi import application

        to_app: asyncio.Queue = asyncio.Queue()
        from_app: asyncio.Queue = asyncio.Queue()

        async def lifespan_receive():
            return await to_app.get()

        async def lifespan_send(message):
            await from_app.put(message)

        lifespan = asyncio.ensure_future(
            application({"type": "lifespan", "asgi": {"version": "3.0"}}, lifespan_receive, lifespan_send)
        )
        await to_app.put({"type": "lifespan.startup"})
        started = await asyncio.wait_for(from_app.get(), timeout=30)
        self.assertEqual(started["type"], "lifespan.startup.complete", started)
        try:
            base = "https://e2eflow.kolberg.uz/mcp"
            host = "e2eflow.kolberg.uz"

            async def call(method, path, **kw):
                return await _asgi_request(application, host, method, path, **kw)

            if True:
                r = await call("POST", "/mcp/register", json_body={
                    "client_name": "e2e",
                    "redirect_uris": [_E2E_REDIRECT],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                })
                self.assertEqual(r.status_code, 201, r.text)
                client_id = r.json()["client_id"]

                verifier = secrets.token_urlsafe(48)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                r = await call("GET", "/mcp/authorize", params={
                    "response_type": "code", "client_id": client_id, "redirect_uri": _E2E_REDIRECT,
                    "code_challenge": challenge, "code_challenge_method": "S256",
                    "state": "st", "scope": "mcp", "resource": base,
                })
                self.assertEqual(r.status_code, 302, r.text)
                self.assertTrue(r.headers["location"].startswith(f"{base}/login/?t="), r.headers["location"])

                # The OTP login itself is covered by McpTenantLoginViewTests; issue its result directly.
                code = await sync_to_async(create_authorization_code, thread_sensitive=True)(
                    client_id=client_id, user_id=self.user.id, tenant_id=self.tenant.id,
                    redirect_uri=_E2E_REDIRECT, redirect_uri_provided_explicitly=True,
                    code_challenge=challenge, code_challenge_method="S256", scopes=["mcp"], state="st",
                )
                r = await call("POST", "/mcp/token", form={
                    "grant_type": "authorization_code", "code": code, "redirect_uri": _E2E_REDIRECT,
                    "client_id": client_id, "code_verifier": verifier, "resource": base,
                })
                self.assertEqual(r.status_code, 200, r.text)
                access = r.json()["access_token"]

                headers = {
                    "Authorization": f"Bearer {access}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                }
                r = await call("POST", "/mcp/", headers=headers, json_body={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "e2e", "version": "1"}},
                })
                self.assertEqual(r.status_code, 200, r.text)

                r = await call("POST", "/mcp/", headers=headers, json_body={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                self.assertEqual(r.status_code, 200, r.text)
                names = {t["name"] for t in _rpc_payload(r)["result"]["tools"]}
                self.assertIn("get_current_tenant", names)
                self.assertIn("list_requests", names)
                self.assertNotIn("list_payroll_documents", names)  # payroll enabled, but not for requester
                self.assertNotIn("list_user_roles", names)

                r = await call("POST", "/mcp/", headers=headers, json_body={
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "get_current_tenant", "arguments": {}},
                })
                self.assertEqual(r.status_code, 200, r.text)
                result = _rpc_payload(r)["result"]
                self.assertFalse(result.get("isError"), result)
                self.assertIn("e2eflow", "".join(c.get("text", "") for c in result["content"]))

                r = await call("POST", "/mcp/", headers=headers, json_body={
                    "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "list_payroll_documents", "arguments": {}},
                })
                result = _rpc_payload(r)["result"]
                self.assertTrue(result.get("isError"), result)
                self.assertIn("Unknown tool: list_payroll_documents", "".join(c.get("text", "") for c in result["content"]))

                r = await call("POST", "/mcp/", headers={**headers, "Authorization": f"Bearer {access}x"},
                                    json_body={"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}})
                self.assertEqual(r.status_code, 401)
        finally:
            await to_app.put({"type": "lifespan.shutdown"})
            await asyncio.wait_for(from_app.get(), timeout=30)
            await asyncio.wait_for(lifespan, timeout=30)
