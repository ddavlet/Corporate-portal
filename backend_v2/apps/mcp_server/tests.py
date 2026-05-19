from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.mcp_server.utils import json_safe, validate_date


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
