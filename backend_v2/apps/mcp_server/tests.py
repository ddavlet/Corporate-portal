from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import Client, TestCase, override_settings

from apps.mcp_server.utils import json_safe, validate_date
from config.asgi import _is_mcp_protocol_path, _is_well_known_oauth_path


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


class McpAsgiPathRoutingTests(TestCase):
    def test_fastmcp_paths(self):
        for path in ("/mcp", "/mcp/", "/mcp/authorize", "/mcp/token", "/mcp/register"):
            self.assertTrue(_is_mcp_protocol_path(path), path)

    def test_django_paths_not_fastmcp(self):
        for path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource",
            "/mcp/oauth/login/",
            "/oauth/mcp/login/",
            "/mcp/login/",
            "/mcp/login",
            "/api/health/",
        ):
            self.assertFalse(_is_mcp_protocol_path(path), path)

    def test_well_known_paths(self):
        self.assertTrue(_is_well_known_oauth_path("/.well-known/oauth-authorization-server"))
        self.assertTrue(_is_well_known_oauth_path("/.well-known/oauth-protected-resource/"))
        self.assertFalse(_is_well_known_oauth_path("/mcp/.well-known/oauth-authorization-server"))


@override_settings(
    MCP_BASE_URL="https://api.kolberg.uz/mcp",
    MCP_RESOURCE_URL="https://api.kolberg.uz/mcp",
    MCP_OAUTH_LOGIN_URL="https://api.kolberg.uz/mcp/oauth/login",
)
class McpOAuthMetadataTests(TestCase):
    def setUp(self):
        self.client = Client()

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
        r = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["authorization_endpoint"], "https://api.kolberg.uz/mcp/authorize")

        r = self.client.get("/.well-known/oauth-protected-resource")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["resource"], "https://api.kolberg.uz/mcp")

    def test_oauth_login_page_without_token_returns_400(self):
        r = self.client.get("/mcp/oauth/login/")
        self.assertEqual(r.status_code, 400)

    def test_legacy_login_redirects_to_oauth_login(self):
        for legacy in ("/mcp/login/?t=test", "/oauth/mcp/login/?t=test"):
            r = self.client.get(legacy)
            self.assertEqual(r.status_code, 301, legacy)
            self.assertTrue(
                r["Location"].startswith("https://api.kolberg.uz/mcp/oauth/login/"),
                r["Location"],
            )


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
