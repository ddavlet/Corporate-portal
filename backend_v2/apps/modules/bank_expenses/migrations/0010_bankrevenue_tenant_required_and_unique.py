import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0009_bankrevenue_backfill_tenant"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="bankrevenue",
            name="uniq_bank_revenue_doc_no_doc_date_kredit_turnover",
        ),
        migrations.AddConstraint(
            model_name="bankrevenue",
            constraint=models.UniqueConstraint(
                fields=("tenant", "doc_no", "doc_date", "kredit_turnover"),
                name="uniq_bank_revenue_tenant_doc_no_doc_date_kredit_turnover",
            ),
        ),
        migrations.AlterField(
            model_name="bankrevenue",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="bank_revenues",
                to="tenants.tenant",
            ),
        ),
        migrations.RemoveField(
            model_name="bankrevenue",
            name="tenant_subdomain",
        ),
    ]
