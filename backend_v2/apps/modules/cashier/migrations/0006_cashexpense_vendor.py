import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cashier", "0005_cashexpense_confirmed"),
        ("vendors", "0002_enable_vendors_for_requests_tenants"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE cash_expenses
                    ADD COLUMN IF NOT EXISTS vendor_id bigint NULL
                    """,
                    reverse_sql="""
                    ALTER TABLE cash_expenses
                    DROP COLUMN IF EXISTS vendor_id
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="cashexpense",
                    name="vendor",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cash_expenses",
                        to="vendors.vendor",
                    ),
                ),
            ],
        ),
    ]
