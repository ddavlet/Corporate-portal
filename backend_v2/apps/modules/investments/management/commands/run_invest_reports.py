"""Send the weekly investor reports due this hour and exit (backend_cron, hourly).

Examples:
    python manage.py run_invest_reports
    python manage.py run_invest_reports --now=2026-10-26T10:00:00+05:00 --tenant=lemonaqua
    python manage.py run_invest_reports --dry-run --now=2026-10-26T10:00:00+05:00

--dry-run prints the report of every active tenant with the investments module (even when the
report is not switched on yet) and neither sends nor writes anything: use it to compare with n8n.
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.investments.investor_report_jobs import dry_run_reports, process_due_reports


class Command(BaseCommand):
    help = "Send weekly investor reports to tenant Telegram groups."

    def add_arguments(self, parser):
        parser.add_argument("--now", help="ISO 8601 timestamp to treat as 'now'. Defaults to current time.")
        parser.add_argument("--tenant", help="Only this tenant (subdomain).")
        parser.add_argument("--dry-run", action="store_true", help="Print texts; send and write nothing.")

    def handle(self, *args, **options):
        now_dt = None
        raw_now = options.get("now")
        if raw_now:
            try:
                now_dt = dt.datetime.fromisoformat(raw_now)
            except ValueError as exc:
                raise CommandError(f"Invalid --now value: {exc}") from exc
            if now_dt.tzinfo is None:
                now_dt = timezone.make_aware(now_dt)
        tenant = options.get("tenant") or None

        if options.get("dry_run"):
            for item in dry_run_reports(now_dt=now_dt, tenant_subdomain=tenant):
                due = "yes" if item.is_due else "no"
                self.stdout.write(f"===== {item.tenant.subdomain} chat={item.chat_id or '-'} due={due} =====")
                self.stdout.write(item.text if not item.error else f"ERROR: {item.error}")
                self.stdout.write("")
            return

        sent = process_due_reports(now_dt=now_dt, tenant_subdomain=tenant)
        self.stdout.write(self.style.SUCCESS(f"Investor reports dispatched: {sent}"))
