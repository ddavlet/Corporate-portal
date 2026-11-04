from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.modules.kapitalbank.models import BankAccountLink
from apps.modules.kapitalbank.runner import RefreshReport, RunReport

RUN = "apps.modules.kapitalbank.runner.run"
REFRESH = "apps.modules.kapitalbank.runner.refresh_accounts"


def _call(*args):
    out = StringIO()
    call_command("import_kapitalbank_statements", *args, stdout=out)
    return out.getvalue()


class ImportKapitalbankStatementsCommandTests(SimpleTestCase):
    def test_manual_requires_tenant_and_dates(self):
        cases = {
            "no tenant": ["--mode", "manual", "--date", "2026-10-20"],
            "no dates": ["--mode", "manual", "--tenant", "kolberg"],
            "from after to": ["--mode", "manual", "--tenant", "kolberg", "--from", "2026-10-22", "--to", "2026-10-20"],
            "only from": ["--mode", "manual", "--tenant", "kolberg", "--from", "2026-10-22"],
            "dates in daytime": ["--mode", "daytime", "--date", "2026-10-20"],
            "dates in nightly": ["--mode", "nightly", "--from", "2026-10-20", "--to", "2026-10-21"],
            "date and range": ["--mode", "manual", "--tenant", "kolberg", "--date", "2026-10-20",
                               "--from", "2026-10-20", "--to", "2026-10-21"],
            "invalid date": ["--mode", "manual", "--tenant", "kolberg", "--date", "20-10-2026"],
            "invalid now": ["--mode", "daytime", "--now", "not-a-date"],
        }
        for name, args in cases.items():
            with self.subTest(name), mock.patch(RUN) as run:
                with self.assertRaises(CommandError):
                    _call(*args)
                run.assert_not_called()

    def test_scheduled_modes_pass_no_days(self):
        for mode in ("daytime", "nightly"):
            with self.subTest(mode), mock.patch(RUN, return_value=RunReport()) as run:
                _call("--mode", mode)
            kwargs = run.call_args.kwargs
            self.assertEqual(kwargs["mode"], mode)
            self.assertIsNone(kwargs["days"])
            self.assertFalse(kwargs["dry_run"])

    def test_manual_single_date(self):
        with mock.patch(RUN, return_value=RunReport()) as run:
            _call("--mode", "manual", "--tenant", "kolberg", "--date", "2026-10-20")
        self.assertEqual(run.call_args.kwargs["days"], [date(2026, 10, 20)])

    def test_manual_range_limit(self):
        base = ["--mode", "manual", "--tenant", "kolberg", "--from", "2026-10-01"]
        with mock.patch(RUN, return_value=RunReport()) as run:
            _call(*base, "--to", "2026-10-31")
            self.assertEqual(len(run.call_args.kwargs["days"]), 31)
            with self.assertRaises(CommandError):
                _call(*base, "--to", "2026-11-01")

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
        with mock.patch(RUN, return_value=report) as run:
            output = _call("--mode", "daytime", "--dry-run", "--now", "2026-10-20T10:00:00")
        now = run.call_args.kwargs["now"]
        self.assertTrue(run.call_args.kwargs["dry_run"])
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset(), timedelta(hours=5))
        self.assertEqual((now.hour, now.minute), (10, 0))
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

    def test_mode_required_without_refresh_accounts(self):
        with mock.patch(RUN) as run, self.assertRaises(CommandError):
            _call()
        run.assert_not_called()

    def test_refresh_accounts_argument_rules(self):
        cases = {
            "no tenant": ["--refresh-accounts"],
            "with dry-run": ["--refresh-accounts", "--tenant", "kp", "--dry-run"],
            "with mode": ["--refresh-accounts", "--tenant", "kp", "--mode", "nightly"],
            "with date": ["--refresh-accounts", "--tenant", "kp", "--date", "2026-10-20"],
        }
        for name, args in cases.items():
            with self.subTest(name), mock.patch(REFRESH) as refresh, mock.patch(RUN) as run:
                with self.assertRaises(CommandError):
                    _call(*args)
                refresh.assert_not_called()
                run.assert_not_called()

    def test_refresh_accounts_prints_list_and_runs_no_import(self):
        links = [
            BankAccountLink(
                account_no="20208000504843803001", branch="01158", name="Расчетный счет 1", currency="UZS",
                last_balance=Decimal("460000.5"), decision=BankAccountLink.LINKED,
            ),
            BankAccountLink(account_no="20208000904843803009", branch="01158", name="Новый", currency="USD"),
        ]
        with mock.patch(REFRESH, return_value=RefreshReport(links=links)) as refresh, mock.patch(RUN) as run:
            output = _call("--refresh-accounts", "--tenant", "kp")
        run.assert_not_called()
        self.assertEqual(refresh.call_args.kwargs["tenant_subdomain"], "kp")
        self.assertIn("20208000504843803001 | 01158 | Расчетный счет 1 | UZS | 460000.50 | linked", output)
        self.assertIn("20208000904843803009 | 01158 | Новый | USD | - | pending", output)

    def test_refresh_accounts_error_is_command_error(self):
        with mock.patch(REFRESH, return_value=RefreshReport(error="Пароль банка не задан")):
            with self.assertRaises(CommandError) as ctx:
                _call("--refresh-accounts", "--tenant", "kp")
        self.assertIn("Пароль", str(ctx.exception))
