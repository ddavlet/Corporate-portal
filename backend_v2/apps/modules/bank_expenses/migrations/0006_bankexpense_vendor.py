import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0005_clear_ordering_options"),
        ("vendors", "0002_enable_vendors_for_requests_tenants"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE bank_expenses
                    ADD COLUMN IF NOT EXISTS vendor_id bigint NULL
                    """,
                    reverse_sql="""
                    ALTER TABLE bank_expenses
                    DROP COLUMN IF EXISTS vendor_id
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="bankexpense",
                    name="vendor",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bank_expenses",
                        to="vendors.vendor",
                    ),
                ),
            ],
        ),
    ]
