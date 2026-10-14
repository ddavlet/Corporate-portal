"""PostgreSQL id sequences vs. rows inserted with an explicit primary key.

An INSERT that supplies its own id (n8n imports send source-system ids) does not advance the
table's sequence, so the next ordinary INSERT can be handed an id that is already taken and
fail with a duplicate primary key. These helpers detect and close that gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import connection


@dataclass(frozen=True)
class SequenceLag:
    table: str
    max_id: int
    sequence_value: int


def _sequence_name(cursor, model) -> str | None:
    cursor.execute(
        "SELECT pg_get_serial_sequence(%s, %s)",
        [connection.ops.quote_name(model._meta.db_table), model._meta.pk.column],
    )
    row = cursor.fetchone()
    return row[0] if row else None


def find_sequence_lag(model) -> SequenceLag | None:
    """The gap, when the table already holds ids the sequence has not handed out yet."""
    if connection.vendor != "postgresql":
        return None
    table = connection.ops.quote_name(model._meta.db_table)
    column = connection.ops.quote_name(model._meta.pk.column)
    with connection.cursor() as cursor:
        sequence = _sequence_name(cursor, model)
        if sequence is None:
            return None
        cursor.execute(f"SELECT MAX({column}), pg_sequence_last_value(%s::regclass) FROM {table}", [sequence])
        max_id, last_value = cursor.fetchone()
    if max_id is None or (last_value is not None and last_value >= max_id):
        return None
    return SequenceLag(table=model._meta.db_table, max_id=max_id, sequence_value=last_value or 0)


def ensure_sequence_ahead(model) -> None:
    """Move the id sequence past the highest stored id; never moves it backwards."""
    if connection.vendor != "postgresql":
        return
    table = connection.ops.quote_name(model._meta.db_table)
    column = connection.ops.quote_name(model._meta.pk.column)
    with connection.cursor() as cursor:
        sequence = _sequence_name(cursor, model)
        if sequence is None:
            return
        cursor.execute(
            f"SELECT setval(%s::regclass, GREATEST("
            f"(SELECT COALESCE(MAX({column}), 0) FROM {table}), "
            f"COALESCE(pg_sequence_last_value(%s::regclass), 0), 1))",
            [sequence, sequence],
        )
