import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("corporate_card", "0007_card_external_id"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="cardexpense",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="card_expenses",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="cardrevenue",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="card_revenues",
                        to="tenants.tenant",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(
                    ("corporate_card", "CardExpense", "tenant"),
                    ("corporate_card", "CardRevenue", "tenant"),
                ),
            ],
        ),
    ]
