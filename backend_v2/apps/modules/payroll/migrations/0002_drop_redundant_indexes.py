import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0001_initial"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payrolldocument",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="payroll_documents",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="payrollline",
            name="document",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="lines",
                to="payroll.payrolldocument",
            ),
        ),
    ]
