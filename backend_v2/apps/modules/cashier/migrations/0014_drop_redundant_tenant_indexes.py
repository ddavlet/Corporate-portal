import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("cashier", "0013_cashrevenue_source_year_unique"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="cashexpense",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cash_expenses",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="cashrevenue",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cash_revenues",
                        to="tenants.tenant",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(
                    ("cashier", "CashExpense", "tenant"),
                    ("cashier", "CashRevenue", "tenant"),
                ),
            ],
        ),
    ]
