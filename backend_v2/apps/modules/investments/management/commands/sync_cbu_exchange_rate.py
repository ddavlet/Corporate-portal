"""Archive the CBU RUz USD/UZS rate for yesterday (final) and today (current).

Intended to be invoked by the `backend_cron` Docker service (see
backend_v2/cron/crontab) — daily, after CBU typically publishes its bulletin.

CBU's "today" rate can still be revised during the day, so each run refreshes
both dates: yesterday becomes final (won't change again), today is the best
currently-available value and gets refreshed again tomorrow when it, in turn,
becomes "yesterday".

Examples:
    python manage.py sync_cbu_exchange_rate
"""

from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand

from apps.modules.investments.models import CbuExchangeRate
from apps.modules.investments.services import CbuRateFetchError, fetch_cbu_usd_uzs_rate, tashkent_today

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Archive CBU RUz USD/UZS rate for yesterday (final) and today (current) into CbuExchangeRate."

    def handle(self, *args, **options):
        today = tashkent_today()
        yesterday = today - dt.timedelta(days=1)

        for rate_date in (yesterday, today):
            try:
                rate = fetch_cbu_usd_uzs_rate(rate_date=rate_date)
            except CbuRateFetchError:
                logger.exception("sync_cbu_exchange_rate: failed to fetch CBU rate for %s", rate_date)
                self.stderr.write(self.style.WARNING(f"Failed to fetch CBU rate for {rate_date}, skipping."))
                continue

            _, created = CbuExchangeRate.objects.update_or_create(
                date=rate_date,
                defaults={"usd_uzs_rate": rate},
            )
            action = "created" if created else "updated"
            self.stdout.write(f"{action} CbuExchangeRate({rate_date}) = {rate}")
