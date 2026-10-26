"""Kapitalbank statement import: scheduled (daytime/nightly) and manual/dry-run runs."""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.kapitalbank import runner

MAX_MANUAL_DAYS = 31


def _parse_date(option: str, raw: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise CommandError(f"Invalid {option} value (expected YYYY-MM-DD): {raw}") from exc


class Command(BaseCommand):
    help = (
        "Import Kapitalbank statements into the portal (daytime, nightly or manual for a tenant), "
        "or refresh one tenant's bank account list (--refresh-accounts --tenant <subdomain>)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=["daytime", "nightly", "manual"], help="Required unless --refresh-accounts.")
        parser.add_argument("--tenant", help="Tenant subdomain (required for manual mode).")
        parser.add_argument("--date", help="Single day YYYY-MM-DD (manual mode).")
        parser.add_argument("--from", dest="date_from", help="Range start YYYY-MM-DD (manual mode).")
        parser.add_argument("--to", dest="date_to", help="Range end YYYY-MM-DD (manual mode).")
        parser.add_argument("--dry-run", action="store_true", help="Create nothing; print what would change.")
        parser.add_argument("--now", help="ISO 8601 timestamp to treat as 'now'. Defaults to current time.")
        parser.add_argument(
            "--refresh-accounts",
            action="store_true",
            help=(
                "Only refresh the bank account list of --tenant (even if the import is disabled) and print it. "
                "Writes BankAccountLink rows only: new accounts PENDING, existing ones keep their decision."
            ),
        )

    def handle(self, *args, **options):
        if options["refresh_accounts"]:
            self._refresh_accounts(options)
            return
        mode = options["mode"]
        if not mode:
            raise CommandError("--mode is required (or use --refresh-accounts --tenant <subdomain>)")
        now = self._parse_now(options.get("now"))
        days = self._resolve_days(mode, options)
        report = runner.run(
            mode=mode,
            now=now,
            tenant_subdomain=options.get("tenant"),
            days=days,
            dry_run=options["dry_run"],
        )
        self._print_report(report, options["dry_run"])

    def _refresh_accounts(self, options):
        tenant = options.get("tenant")
        if not tenant:
            raise CommandError("--refresh-accounts requires --tenant")
        if options["dry_run"]:
            raise CommandError("--refresh-accounts cannot be combined with --dry-run (it writes the account list)")
        if options.get("mode") or options.get("date") or options.get("date_from") or options.get("date_to"):
            raise CommandError("--refresh-accounts loads no statements: do not pass --mode/--date/--from/--to")
        report = runner.refresh_accounts(tenant_subdomain=tenant, now=self._parse_now(options.get("now")))
        if report.skipped_locked:
            self.stdout.write("Another Kapitalbank run holds the lock; the account list was not refreshed.")
            return
        if report.error:
            raise CommandError(report.error)
        self.stdout.write(f"Kapitalbank accounts of {tenant}: {len(report.links)}")
        self.stdout.write("account_no | branch | name | currency | balance | decision")
        for link in report.links:
            balance = "-" if link.last_balance is None else f"{link.last_balance:.2f}"
            self.stdout.write(
                f"{link.account_no} | {link.branch} | {link.name} | {link.currency} | {balance} | {link.decision}"
            )

    @staticmethod
    def _parse_now(raw):
        if not raw:
            return timezone.now()
        try:
            value = dt.datetime.fromisoformat(raw)
        except ValueError as exc:
            raise CommandError(f"Invalid --now value: {exc}") from exc
        if value.tzinfo is None:
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value

    @staticmethod
    def _resolve_days(mode, options):
        day, start, end = options.get("date"), options.get("date_from"), options.get("date_to")
        if mode != "manual":
            if day or start or end:
                raise CommandError("--date/--from/--to are only allowed with --mode manual")
            return None
        if not options.get("tenant"):
            raise CommandError("--mode manual requires --tenant")
        if day and (start or end):
            raise CommandError("Use either --date or --from/--to, not both")
        if day:
            return [_parse_date("--date", day)]
        if not (start and end):
            raise CommandError("--mode manual requires --date or both --from and --to")
        first, last = _parse_date("--from", start), _parse_date("--to", end)
        if first > last:
            raise CommandError("--from must not be after --to")
        count = (last - first).days + 1
        if count > MAX_MANUAL_DAYS:
            raise CommandError(f"Range is limited to {MAX_MANUAL_DAYS} days (got {count})")
        return [first + dt.timedelta(days=n) for n in range(count)]

    def _print_report(self, report, dry_run):
        if report.skipped_locked:
            self.stdout.write("Another Kapitalbank run holds the lock; this run was skipped.")
            return
        self.stdout.write(
            f"Kapitalbank import{' (dry-run)' if dry_run else ''}: "
            f"accounts_ok={report.accounts_ok} accounts_failed={report.accounts_failed} "
            f"created={report.created} alerts={report.alerts}"
        )
        if not dry_run:
            return
        for d in report.details:
            would = d.get("would_create") or []
            ids = ", ".join(str(i.get("external_id")) for i in would)
            self.stdout.write(
                f"{d['tenant']} {d['account_no']} {d['day']}: would_create={len(would)}"
                f"{' [' + ids + ']' if ids else ''} skipped_existing={d.get('skipped_existing')} "
                f"saldo_out={d.get('saldo_out') if d.get('saldo_out') is not None else '-'}"
                + (f" portal_balance={d['portal_balance']}" if "portal_balance" in d else "")
            )
            diffs = d.get("field_diffs") or []
            self.stdout.write(f"  field_diffs={len(diffs)}")
            for diff in diffs:
                self.stdout.write(
                    f"  field_diffs: {diff['external_id']} {diff['field']}: "
                    f"portal={diff['portal']} bank={diff['bank']}"
                )
