from django.db import migrations, models
from django.db.models import Q


def _column_exists(schema_editor, table: str, column: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
              AND column_name = %s
            """,
            [table, column],
        )
        return cursor.fetchone() is not None


def _index_exists(schema_editor, name: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'i'
              AND c.relname = %s
              AND n.nspname = current_schema()
            """,
            [name],
        )
        return cursor.fetchone() is not None


def apply_bank_external_id(apps, schema_editor):
    # Production may already have external_id columns added outside Django migrations.
    with schema_editor.connection.cursor() as cursor:
        for table in ("bank_expenses", "bank_revenues"):
            if not _column_exists(schema_editor, table, "external_id"):
                cursor.execute(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN external_id varchar(64) DEFAULT '' NOT NULL
                    """
                )
            else:
                cursor.execute(
                    f"""
                    ALTER TABLE {table}
                    ALTER COLUMN external_id TYPE varchar(64),
                    ALTER COLUMN external_id SET DEFAULT '',
                    ALTER COLUMN external_id SET NOT NULL
                    """
                )
        for index_name, table in (
            ("uniq_bank_expense_tenant_external_id", "bank_expenses"),
            ("uniq_bank_revenue_tenant_external_id", "bank_revenues"),
        ):
            if not _index_exists(schema_editor, index_name):
                cursor.execute(
                    f"""
                    CREATE UNIQUE INDEX {index_name}
                    ON {table} (tenant_id, external_id)
                    WHERE NOT (external_id = '')
                    """
                )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("bank_expenses", "0014_bankexpense_unique_per_tenant"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="bankexpense",
                    name="external_id",
                    field=models.CharField(blank=True, default="", max_length=64),
                ),
                migrations.AddField(
                    model_name="bankrevenue",
                    name="external_id",
                    field=models.CharField(blank=True, default="", max_length=64),
                ),
                migrations.AddConstraint(
                    model_name="bankexpense",
                    constraint=models.UniqueConstraint(
                        condition=~Q(external_id=""),
                        fields=("tenant", "external_id"),
                        name="uniq_bank_expense_tenant_external_id",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="bankrevenue",
                    constraint=models.UniqueConstraint(
                        condition=~Q(external_id=""),
                        fields=("tenant", "external_id"),
                        name="uniq_bank_revenue_tenant_external_id",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(apply_bank_external_id, noop_reverse),
            ],
        ),
    ]
