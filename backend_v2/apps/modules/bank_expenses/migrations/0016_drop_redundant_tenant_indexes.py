import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0015_bank_external_id"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="bankexpense",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bank_expenses",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="bankrevenue",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bank_revenues",
                        to="tenants.tenant",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(
                    ("bank_expenses", "BankExpense", "tenant"),
                    ("bank_expenses", "BankRevenue", "tenant"),
                ),
            ],
        ),
    ]
