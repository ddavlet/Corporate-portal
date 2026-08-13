import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cashier", "0013_cashrevenue_source_year_unique"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
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
    ]
