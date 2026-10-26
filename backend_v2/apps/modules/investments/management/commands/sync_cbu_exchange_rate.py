"""Archive the CBU RUz USD/UZS rate for yesterday (final) and today (current).

Intended to be invoked by the `backend_cron` Docker service (see
backend_v2/cron/crontab) — daily, after CBU typically publishes its bulletin.

CBU's "today" rate can still be revised during the day, so each run refreshes
both dates: yesterday becomes final (won't change again), today is the best
currently-available value and gets refreshed again tomorrow when it, in turn,
becomes "yesterday".

With ``--fill-gaps-days N`` the run also fetches dates of the last N days that are
missing from the archive (e.g. while cbu.uz was down) — portal lists and reports read
rates only from the archive. It stops at the first failure so an unreachable CBU costs
one timeout, not N.

Examples:
    python manage.py sync_cbu_exchange_rate
    python manage.py sync_cbu_exchange_rate --fill-gaps-days 14
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

    def add_arguments(self, parser):
        parser.add_argument(
            "--fill-gaps-days",
            type=int,
            default=0,
            help="Also fetch dates of the last N days missing from the archive (stops at the first failure).",
        )

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

        fill_days = max(0, int(options.get("fill_gaps_days") or 0))
        if fill_days:
            self._fill_gaps(start=today - dt.timedelta(days=fill_days), end=today - dt.timedelta(days=2))

    def _fill_gaps(self, *, start: dt.date, end: dt.date) -> None:
        if end < start:
            return
        archived = set(CbuExchangeRate.objects.filter(date__gte=start, date__lte=end).values_list("date", flat=True))
        day = start
        while day <= end:
            if day not in archived:
                try:
                    rate = fetch_cbu_usd_uzs_rate(rate_date=day)
                except CbuRateFetchError:
                    logger.exception("sync_cbu_exchange_rate: failed to fill gap %s, stopping", day)
                    self.stderr.write(self.style.WARNING(f"Failed to fetch CBU rate for {day}, gaps left for next run."))
                    return
                CbuExchangeRate.objects.update_or_create(date=day, defaults={"usd_uzs_rate": rate})
                self.stdout.write(f"filled CbuExchangeRate({day}) = {rate}")
            day += dt.timedelta(days=1)
