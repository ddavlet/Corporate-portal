import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0012_drop_legacy_vendor_inn_transfer_unique_constraint"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="vendor",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vendor_directory",
                        to="tenants.tenant",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(("vendors", "Vendor", "tenant")),
            ],
        ),
    ]
