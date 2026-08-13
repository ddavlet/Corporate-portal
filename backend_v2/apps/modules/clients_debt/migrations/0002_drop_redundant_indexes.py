import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("clients_debt", "0001_initial"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="clientdebtsnapshot", name="clients_debt_tenant_date_idx"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="clientdebtsnapshot",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="client_debt_snapshots",
                        to="tenants.tenant",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(("clients_debt", "ClientDebtSnapshot", "tenant")),
            ],
        ),
    ]
