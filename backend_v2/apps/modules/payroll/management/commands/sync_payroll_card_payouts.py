"""Salary card payouts from the Kapitalbank payroll transit account (23106): hourly, nightly or manual."""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.payroll import card_sync

MAX_MANUAL_DAYS = 120


class Command(BaseCommand):
    help = (
        "Load salary card payouts from the Kapitalbank payroll transit account (23106) and attach them "
        "to payroll documents. hourly: yesterday and today; nightly: 40 days, bank payroll directory, "
        "regrouping; manual: from --since to today (with --dry-run nothing is saved and nothing is sent)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--mode", required=True, choices=["hourly", "nightly", "manual"])
        parser.add_argument("--tenant", help="Tenant subdomain: load only the transit accounts this tenant sees.")
        parser.add_argument("--since", help="First day YYYY-MM-DD (manual mode only).")
        parser.add_argument("--dry-run", action="store_true", help="Roll everything back; send no alerts.")
        parser.add_argument("--now", help="ISO 8601 timestamp to treat as 'now'. Defaults to current time.")

    def handle(self, *args, **options):
        mode = options["mode"]
        now = self._parse_now(options.get("now"))
        since = self._parse_since(mode, options.get("since"), now)
        report = card_sync.sync(
            mode=mode, now=now, since=since, tenant_subdomain=options.get("tenant"), dry_run=options["dry_run"]
        )
        if report.skipped_locked:
            self.stdout.write("Another payroll card sync holds the lock; this run was skipped.")
            return
        # Counters only: no names, card accounts or amounts per person.
        self.stdout.write(
            f"Payroll card sync{' (dry-run)' if options['dry_run'] else ''}: "
            f"accounts_ok={report.accounts_ok} accounts_failed={report.accounts_failed} "
            f"batches_created={report.batches_created} payouts_created={report.payouts_created} "
            f"grouped={report.grouped} tenants_resolved={report.tenants_resolved} "
            f"employees_matched={report.employees_matched} attached={report.attached} "
            f"closed={report.closed} alerts={report.alerts}"
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
    def _parse_since(mode, raw, now):
        if mode != "manual":
            if raw:
                raise CommandError("--since is only allowed with --mode manual")
            return None
        if not raw:
            raise CommandError("--mode manual requires --since YYYY-MM-DD")
        try:
            since = dt.date.fromisoformat(raw)
        except ValueError as exc:
            raise CommandError(f"Invalid --since value (expected YYYY-MM-DD): {raw}") from exc
        today = timezone.localtime(now).date()
        if since > today:
            raise CommandError("--since must not be in the future")
        if (today - since).days + 1 > MAX_MANUAL_DAYS:
            raise CommandError(f"--since is limited to {MAX_MANUAL_DAYS} days back")
        return since
