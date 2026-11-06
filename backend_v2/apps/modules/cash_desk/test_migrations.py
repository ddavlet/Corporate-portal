from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class MigrationsInSyncTests(TestCase):
    def test_no_missing_migrations_for_cash_desk(self):
        out = StringIO()
        try:
            call_command("makemigrations", "cash_desk", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"cash_desk models and migrations are out of sync:\n{out.getvalue()}")
