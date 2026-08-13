"""Safe index-only schema helpers for Django migrations.

``AlterField(db_index=False)`` on a ForeignKey makes Django drop and recreate
the FK constraint by a computed name. Production constraint names often differ,
so migrate fails while trying to ``DROP CONSTRAINT`` that does not exist.

These helpers only ``DROP INDEX IF EXISTS`` for a non-unique, non-partial,
single-column btree that is not backing a constraint. Rows and FKs stay.
"""

from __future__ import annotations

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def drop_fk_index_operation(*targets):
    """Database-only operation: drop unconstrained single-column FK indexes."""

    def forwards(apps, schema_editor):
        drop_unconstrained_fk_indexes(apps, schema_editor, *targets)

    return migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop)


def drop_unconstrained_fk_indexes(apps, schema_editor: BaseDatabaseSchemaEditor, *targets):
    """Drop redundant single-column FK indexes.

    ``targets`` are ``(app_label, model_name, field_name)`` tuples using the
    historical model state of the calling migration.
    """
    if schema_editor.connection.vendor != "postgresql":
        return

    quote_name = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        for app_label, model_name, field_name in targets:
            model = apps.get_model(app_label, model_name)
            field = model._meta.get_field(field_name)
            table = model._meta.db_table
            column = field.column
            cursor.execute(
                """
                SELECT idx.relname
                FROM pg_class tbl
                JOIN pg_namespace nsp ON nsp.oid = tbl.relnamespace
                JOIN pg_index x ON x.indrelid = tbl.oid
                JOIN pg_class idx ON idx.oid = x.indexrelid
                WHERE nsp.nspname = ANY (current_schemas(false))
                  AND tbl.relname = %s
                  AND x.indisunique IS FALSE
                  AND x.indisprimary IS FALSE
                  AND x.indpred IS NULL
                  AND x.indnkeyatts = 1
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pg_constraint c
                      WHERE c.conindid = x.indexrelid
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM pg_attribute att
                      WHERE att.attrelid = tbl.oid
                        AND att.attnum = (x.indkey::int2[])[1]
                        AND att.attname = %s
                  )
                """,
                [table, column],
            )
            for (index_name,) in cursor.fetchall():
                cursor.execute(f"DROP INDEX IF EXISTS {quote_name(index_name)}")
