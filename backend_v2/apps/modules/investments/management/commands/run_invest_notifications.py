"""Run the investment payout notification pass once and exit.

Replaces the in-process daemon thread with a scheduler-friendly one-shot. Intended to be
invoked by cron, systemd timer, or k8s CronJob — typically daily at 09:00 Tashkent.

Examples:
    python manage.py run_invest_notifications
    python manage.py run_invest_notifications --now=2026-05-22T09:00:00+05:00
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.investments.notification_services import process_due_invest_payout_notifications


class Command(BaseCommand):
    help = "Send pending investment-payout notifications (upcoming + overdue) for all tenants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--now",
            help="ISO 8601 timestamp to treat as 'now' (for backfills / tests). Defaults to current time.",
        )

    def handle(self, *args, **options):
        raw_now = options.get("now")
        now_dt: dt.datetime | None = None
        if raw_now:
            try:
                now_dt = dt.datetime.fromisoformat(raw_now)
            except ValueError as exc:
                raise CommandError(f"Invalid --now value: {exc}") from exc
            if now_dt.tzinfo is None:
                now_dt = timezone.make_aware(now_dt)

        sent = process_due_invest_payout_notifications(now_dt=now_dt)
        self.stdout.write(self.style.SUCCESS(f"Investment payout notifications dispatched: {sent}"))
