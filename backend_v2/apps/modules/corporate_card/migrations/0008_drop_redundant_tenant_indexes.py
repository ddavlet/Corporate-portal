import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("corporate_card", "0007_card_external_id"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
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
    ]
