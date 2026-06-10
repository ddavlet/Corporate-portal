"""Soft-delete draft requests older than the retention window.

Replaces manual cleanup with a scheduler-friendly one-shot. Invoked by the
`backend_cron` Docker service (see backend_v2/cron/crontab) — daily at 08:15 Tashkent.

Examples:
    python manage.py purge_expired_draft_requests
    python manage.py purge_expired_draft_requests --now=2026-06-10T08:00:00+05:00
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.requests.draft_retention import purge_expired_draft_requests


class Command(BaseCommand):
    help = "Mark DRAFT requests older than 10 days as DELETED (soft delete)."

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

        deleted = purge_expired_draft_requests(now_dt=now_dt)
        self.stdout.write(self.style.SUCCESS(f"Expired drafts marked DELETED: {deleted}"))
