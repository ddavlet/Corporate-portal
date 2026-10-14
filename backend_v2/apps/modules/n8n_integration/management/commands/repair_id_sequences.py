"""Move id sequences past ids that n8n imports inserted explicitly (dry-run by default).

A lagging sequence makes the next ordinary insert fail with a duplicate primary key — e.g. the
cash-withdrawal «Деньги получены» button could not create its CashRevenue.

Examples:
    python manage.py repair_id_sequences
    python manage.py repair_id_sequences --apply
"""

from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, models

from apps.common.db_sequences import ensure_sequence_ahead, find_sequence_lag


def _sequenced_models():
    for model in apps.get_models():
        meta = model._meta
        if meta.managed and not meta.proxy and isinstance(meta.pk, models.AutoField):
            yield model


class Command(BaseCommand):
    help = "Find tables whose id sequence is behind their highest id; --apply moves the sequence forward."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING("Only PostgreSQL uses id sequences; nothing to check."))
            return
        lagging = [(model, lag) for model in _sequenced_models() if (lag := find_sequence_lag(model)) is not None]
        if not lagging:
            self.stdout.write(self.style.SUCCESS("All id sequences are ahead of their tables."))
            return
        for _, lag in lagging:
            self.stdout.write(f"{lag.table}: max id {lag.max_id}, sequence at {lag.sequence_value}")
        if not options["apply"]:
            self.stdout.write(self.style.WARNING(f"Dry-run: {len(lagging)} table(s) need repair. Re-run with --apply."))
            return
        for model, _ in lagging:
            ensure_sequence_ahead(model)
        self.stdout.write(self.style.SUCCESS(f"Repaired id sequences: {len(lagging)}"))
