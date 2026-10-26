from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.modules.kapitalbank.runner import RunReport

RUN = "apps.modules.kapitalbank.runner.run"


def _call(*args):
    out = StringIO()
    call_command("import_kapitalbank_statements", *args, stdout=out)
    return out.getvalue()


class ImportKapitalbankStatementsCommandTests(SimpleTestCase):
    def test_manual_requires_tenant_and_dates(self):
        with mock.patch(RUN) as run:
            with self.assertRaises(CommandError):
                _call("--mode", "manual", "--date", "2026-10-20")
            with self.assertRaises(CommandError):
                _call("--mode", "manual", "--tenant", "kolberg")
            with self.assertRaises(CommandError):
                _call("--mode", "manual", "--tenant", "kolberg", "--from", "2026-10-22", "--to", "2026-10-20")
            with self.assertRaises(CommandError):
                _call("--mode", "daytime", "--date", "2026-10-20")
            run.assert_not_called()

    def test_manual_range_passes_days(self):
        with mock.patch(RUN, return_value=RunReport()) as run:
            _call("--mode", "manual", "--tenant", "kolberg", "--from", "2026-10-20", "--to", "2026-10-22")
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["days"], [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)])
        self.assertEqual(kwargs["tenant_subdomain"], "kolberg")
        self.assertEqual(kwargs["mode"], "manual")

    def test_dry_run_prints_diffs(self):
        report = RunReport(
            details=[
                {
                    "tenant": "kolberg",
                    "account_no": "20208000",
                    "day": "2026-10-20",
                    "would_create": [{"external_id": "kb-1"}],
                    "skipped_existing": 1,
                    "saldo_out": None,
                    "field_diffs": [{"external_id": "kb-2", "field": "amount", "portal": "1", "bank": "2"}],
                }
            ]
        )
        with mock.patch(RUN, return_value=report):
            output = _call("--mode", "daytime", "--dry-run", "--now", "2026-10-20T10:00:00")
        self.assertIn("field_diffs", output)
        self.assertIn("kb-1", output)

    def test_locked_run_exits_cleanly(self):
        with mock.patch(RUN, return_value=RunReport(skipped_locked=True)):
            self.assertIn("lock", _call("--mode", "nightly"))

    def test_crontab_has_schedule(self):
        crontab = (Path(settings.BASE_DIR) / "cron" / "crontab").read_text()
        tail = "cd /app && python manage.py import_kapitalbank_statements"
        out = ">> /proc/1/fd/1 2>&1"
        for line in (
            f"*/10 6-21 * * 1-5 root {tail} --mode daytime {out}",
            f"0 22 * * 1-5 root {tail} --mode daytime {out}",
            f"0 5 * * * root {tail} --mode nightly {out}",
        ):
            self.assertIn(line, crontab)
