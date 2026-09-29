"""Send overdue cash-withdrawal alerts once and exit (backend_cron, hourly).

Examples:
    python manage.py run_cash_withdrawal_alerts
    python manage.py run_cash_withdrawal_alerts --now=2026-09-28T09:00:00+05:00
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.cash_withdrawals.alerts import process_due_alerts


class Command(BaseCommand):
    help = "Send overdue alerts for cash withdrawals not yet confirmed in the register."

    def add_arguments(self, parser):
        parser.add_argument("--now", help="ISO 8601 timestamp to treat as 'now'. Defaults to current time.")

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
        sent = process_due_alerts(now_dt=now_dt)
        self.stdout.write(self.style.SUCCESS(f"Cash withdrawal alerts dispatched: {sent}"))
