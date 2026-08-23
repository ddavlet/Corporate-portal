"""One-time: backfill the CbuExchangeRate archive for a date range, e.g. from
the start of the current year through today.

Daily archiving is normally handled by sync_cbu_exchange_rate (yesterday +
today only, via cron). This command fills in historical dates that were never
archived -- e.g. after the archive (get_or_fetch_usd_uzs_rate /
CbuExchangeRate) was introduced, to backfill rates predating it.

Only dates missing from the archive are fetched; already-archived dates are
left untouched. Weekends/holidays with no published CBU bulletin are skipped
with a warning (same behavior as sync_cbu_exchange_rate).

Run without --apply first to preview which dates are missing, then with
--apply to actually fetch and write them.

Examples:
    python manage.py backfill_cbu_exchange_rate
    python manage.py backfill_cbu_exchange_rate --date-from=2026-01-01 --date-to=2026-08-23
    python manage.py backfill_cbu_exchange_rate --apply
"""

from __future__ import annotations

import datetime as dt
import time

from django.core.management.base import BaseCommand, CommandError

from apps.modules.investments.models import CbuExchangeRate
from apps.modules.investments.services import CbuRateFetchError, fetch_cbu_usd_uzs_rate, tashkent_today


class Command(BaseCommand):
    help = (
        "Backfill missing CbuExchangeRate archive entries for a date range "
        "(default: start of current year through today)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date-from",
            dest="date_from",
            default=None,
            help="First date to backfill (YYYY-MM-DD). Default: January 1 of the current year (Tashkent).",
        )
        parser.add_argument(
            "--date-to",
            dest="date_to",
            default=None,
            help="Last date to backfill (YYYY-MM-DD, inclusive). Default: today (Tashkent).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Fetch and write missing dates. Without this flag the command only lists what's missing.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.2,
            help="Seconds to sleep between CBU requests when --apply is set (default: 0.2).",
        )

    def handle(self, *args, **options):
        today = tashkent_today()
        date_from = self._parse_date(options["date_from"]) if options["date_from"] else dt.date(today.year, 1, 1)
        date_to = self._parse_date(options["date_to"]) if options["date_to"] else today

        if date_from > date_to:
            raise CommandError(f"--date-from ({date_from}) must not be after --date-to ({date_to}).")

        all_dates = [date_from + dt.timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        archived_dates = set(
            CbuExchangeRate.objects.filter(date__gte=date_from, date__lte=date_to).values_list("date", flat=True)
        )
        missing_dates = [d for d in all_dates if d not in archived_dates]

        self.stdout.write(
            f"Range {date_from} .. {date_to}: {len(all_dates)} days, "
            f"{len(archived_dates)} already archived, {len(missing_dates)} missing."
        )

        if not missing_dates:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill."))
            return

        if not options["apply"]:
            preview = ", ".join(d.isoformat() for d in missing_dates[:10])
            more = f" (+{len(missing_dates) - 10} more)" if len(missing_dates) > 10 else ""
            self.stdout.write(f"Missing dates: {preview}{more}")
            self.stdout.write(
                self.style.WARNING("Dry-run: no changes written. Re-run with --apply to fetch and save.")
            )
            return

        created = 0
        skipped: list[dt.date] = []
        for i, rate_date in enumerate(missing_dates):
            try:
                rate = fetch_cbu_usd_uzs_rate(rate_date=rate_date)
            except CbuRateFetchError as exc:
                skipped.append(rate_date)
                self.stderr.write(self.style.WARNING(f"Skipping {rate_date}: {exc}"))
                continue

            CbuExchangeRate.objects.update_or_create(date=rate_date, defaults={"usd_uzs_rate": rate})
            created += 1
            self.stdout.write(f"created CbuExchangeRate({rate_date}) = {rate}")

            if options["sleep"] and i < len(missing_dates) - 1:
                time.sleep(options["sleep"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill done: {created} created, {len(skipped)} skipped (no bulletin / weekend / holiday)."
            )
        )

    @staticmethod
    def _parse_date(value: str) -> dt.date:
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(f"Invalid date {value!r}, expected YYYY-MM-DD.") from exc
