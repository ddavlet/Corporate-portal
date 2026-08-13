import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("contracts", "0002_contract_amount_nullable"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="contract", name="contracts_tenant_vendor_idx"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="contract",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contracts",
                        to="tenants.tenant",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(("contracts", "Contract", "tenant")),
            ],
        ),
    ]
