from django.db import migrations, models


def backfill_expense_calendar(apps, schema_editor):
    BankExpense = apps.get_model("bank_expenses", "BankExpense")
    for row in BankExpense.objects.iterator():
        d = row.doc_date
        BankExpense.objects.filter(pk=row.pk).update(
            expense_year=d.year,
            expense_month=d.month,
            expense_day=d.day,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0006_bankexpense_vendor"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE bank_expenses ADD COLUMN IF NOT EXISTS expense_year integer;
                    ALTER TABLE bank_expenses ADD COLUMN IF NOT EXISTS expense_month smallint;
                    ALTER TABLE bank_expenses ADD COLUMN IF NOT EXISTS expense_day smallint;
                    """,
                    reverse_sql="""
                    ALTER TABLE bank_expenses DROP COLUMN IF EXISTS expense_day;
                    ALTER TABLE bank_expenses DROP COLUMN IF EXISTS expense_month;
                    ALTER TABLE bank_expenses DROP COLUMN IF EXISTS expense_year;
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="bankexpense",
                    name="expense_year",
                    field=models.PositiveIntegerField(default=2000),
                    preserve_default=False,
                ),
                migrations.AddField(
                    model_name="bankexpense",
                    name="expense_month",
                    field=models.PositiveSmallIntegerField(default=1),
                    preserve_default=False,
                ),
                migrations.AddField(
                    model_name="bankexpense",
                    name="expense_day",
                    field=models.PositiveSmallIntegerField(default=1),
                    preserve_default=False,
                ),
            ],
        ),
        migrations.RunPython(backfill_expense_calendar, migrations.RunPython.noop),
    ]
