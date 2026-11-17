from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class MigrationsInSyncTests(TestCase):
    def test_no_missing_migrations_for_corporate_card(self):
        out = StringIO()
        try:
            call_command("makemigrations", "corporate_card", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"corporate_card models and migrations are out of sync:\n{out.getvalue()}")
