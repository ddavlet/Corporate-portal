import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contracts", "0002_contract_amount_nullable"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="contract", name="contracts_tenant_vendor_idx"),
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
    ]
