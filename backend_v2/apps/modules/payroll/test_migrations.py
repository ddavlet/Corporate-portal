import importlib
import os
from io import StringIO
from unittest import skipUnless

from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import TestCase


class MigrationsInSyncTests(TestCase):
    """payroll migrations are hand-written in branches: the models must not drift from them."""

    def test_no_missing_migrations_for_payroll(self):
        out = StringIO()
        try:
            call_command("makemigrations", "payroll", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"payroll models and migrations are out of sync:\n{out.getvalue()}")


@skipUnless(connection.vendor == "postgresql", "Postgres privileges")
class CardTablesRevokeTests(TestCase):
    """0008 revokes the tables with bank personal data from readers that default privileges gave
    them to (the postgres-mcp role), without waiting for the role script to be re-run."""

    def test_readers_lose_select_on_personal_data_tables_only(self):
        role = f"payroll_revoke_probe_{os.getpid()}"
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f"CREATE ROLE {connection.ops.quote_name(role)} NOLOGIN")
        except DatabaseError:
            self.skipTest("the test database user cannot create roles")
        migration = importlib.import_module("apps.modules.payroll.migrations.0008_card_payouts")
        quoted = connection.ops.quote_name(role)
        with connection.cursor() as cursor:
            cursor.execute(f"GRANT SELECT ON TABLE payroll_card_payouts, payroll_bank_employees, payroll_lines TO {quoted}")
        with connection.schema_editor() as editor:
            migration.revoke_personal_data_from_readers(None, editor)
        with connection.cursor() as cursor:
            for table, expected in (
                ("payroll_card_payouts", False),
                ("payroll_bank_employees", False),
                ("payroll_lines", True),
            ):
                cursor.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", [role, table])
                self.assertIs(cursor.fetchone()[0], expected, table)
