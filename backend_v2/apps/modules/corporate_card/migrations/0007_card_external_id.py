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


def apply_card_external_id(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if not _column_exists(schema_editor, "corporate_card_expenses", "external_id"):
            cursor.execute(
                """
                ALTER TABLE corporate_card_expenses
                ADD COLUMN external_id varchar(64) DEFAULT '' NOT NULL
                """
            )
        # CardRevenue.external_id already existed; widen to 64 if shorter.
        cursor.execute(
            """
            ALTER TABLE corporate_card_revenues
            ALTER COLUMN external_id TYPE varchar(64)
            """
        )
        for index_name, table in (
            ("uniq_card_expense_tenant_external_id", "corporate_card_expenses"),
            ("uniq_card_revenue_tenant_external_id", "corporate_card_revenues"),
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
        ("corporate_card", "0006_drop_cardrevenue_duplicate_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="cardexpense",
                    name="external_id",
                    field=models.CharField(blank=True, default="", max_length=64),
                ),
                migrations.AlterField(
                    model_name="cardrevenue",
                    name="external_id",
                    field=models.CharField(blank=True, default="", max_length=64),
                ),
                migrations.AddConstraint(
                    model_name="cardexpense",
                    constraint=models.UniqueConstraint(
                        condition=~Q(external_id=""),
                        fields=("tenant", "external_id"),
                        name="uniq_card_expense_tenant_external_id",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="cardrevenue",
                    constraint=models.UniqueConstraint(
                        condition=~Q(external_id=""),
                        fields=("tenant", "external_id"),
                        name="uniq_card_revenue_tenant_external_id",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(apply_card_external_id, noop_reverse),
            ],
        ),
    ]
