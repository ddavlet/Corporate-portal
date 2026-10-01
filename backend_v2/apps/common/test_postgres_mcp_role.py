import re
from pathlib import Path
from unittest import skipUnless

from django.apps import apps
from django.test import SimpleTestCase

ROLE_SQL = Path(__file__).resolve().parents[3] / "scripts" / "postgres_mcp_create_readonly_role.sql"

# Column names that look like credentials: password hashes, tokens, encrypted secrets, sessions.
SECRET_COLUMN_RE = re.compile(r"(password|secret|token|hash|_enc$|webhook_url|^session_(key|data)$)")

# Matches the pattern but holds no secret.
NOT_SECRET = {
    ("mcp_oauth_client", "token_endpoint_auth_method"),
    ("mcp_oauth_client", "client_secret_expires_at"),  # a timestamp, not the secret
}


# The production container mounts only backend_v2/, so the script is checked in CI only.
@skipUnless(ROLE_SQL.exists(), "scripts/ is not available (backend_v2-only checkout)")
class PostgresMcpReadonlyRoleTests(SimpleTestCase):
    """The Postgres MCP read-only role must not be able to read credentials.

    scripts/postgres_mcp_create_readonly_role.sql grants SELECT on every table and then
    revokes secrets (whole tables or single columns). A new secret-looking model field
    must be added to one of those lists, otherwise it becomes readable through MCP.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sql = ROLE_SQL.read_text()
        tables_block = sql.split("FROM (VALUES", 1)[1].split(") AS t(tbl)", 1)[0]
        cls.hidden_tables = set(re.findall(r"\('([a-z0-9_]+)'\)", tables_block))
        columns_block = sql.split("INSERT INTO mcp_hidden_columns (tbl, col) VALUES", 1)[1].split(";", 1)[0]
        cls.hidden_columns = set(re.findall(r"\('([a-z0-9_]+)',\s*'([a-z0-9_]+)'\)", columns_block))

    def test_known_secrets_are_hidden(self):
        self.assertTrue(
            {"django_session", "accounts_otpchallenge", "mcp_oauth_authorization_code"} <= self.hidden_tables
        )
        self.assertIn(("accounts_user", "password"), self.hidden_columns)
        self.assertIn(("tenant_integration_configs", "n8n_integration_token_enc"), self.hidden_columns)

    def test_every_secret_looking_model_column_is_hidden(self):
        exposed = []
        for model in apps.get_models(include_auto_created=True):
            table = model._meta.db_table
            if table in self.hidden_tables:
                continue
            for field in model._meta.concrete_fields:
                key = (table, field.column)
                if SECRET_COLUMN_RE.search(field.column) and key not in NOT_SECRET and key not in self.hidden_columns:
                    exposed.append(f"{table}.{field.column}")
        self.assertEqual(
            exposed,
            [],
            "Add these columns to mcp_hidden_columns (or NOT_SECRET) in "
            "scripts/postgres_mcp_create_readonly_role.sql",
        )

    def test_hidden_entries_point_to_existing_model_columns(self):
        columns_by_table = {}
        for model in apps.get_models(include_auto_created=True):
            columns_by_table[model._meta.db_table] = {f.column for f in model._meta.concrete_fields}
        self.assertEqual(self.hidden_tables - columns_by_table.keys(), set())
        stale = {(t, c) for t, c in self.hidden_columns if c not in columns_by_table.get(t, set())}
        self.assertEqual(stale, set())
