"""Run the monthly auto-requests pass once and exit.

Replaces the in-process daemon thread with a scheduler-friendly one-shot. Intended to be
invoked by the `backend_cron` Docker service (see backend_v2/cron/crontab) — daily at 08:00 Tashkent.

Examples:
    python manage.py run_auto_requests
    python manage.py run_auto_requests --now=2026-05-22T08:00:00+05:00
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.requests.auto_requests import process_due_auto_requests


class Command(BaseCommand):
    help = "Create auto-request copies for templates whose day-of-month is today (all tenants)."

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

        created = process_due_auto_requests(now_dt=now_dt)
        self.stdout.write(self.style.SUCCESS(f"Auto-request copies created: {created}"))
