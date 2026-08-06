from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("bank_expenses", "0014_bankexpense_unique_per_tenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankexpense",
            name="external_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="bankrevenue",
            name="external_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddConstraint(
            model_name="bankexpense",
            constraint=models.UniqueConstraint(
                condition=~Q(external_id=""),
                fields=("tenant", "external_id"),
                name="uniq_bank_expense_tenant_external_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="bankrevenue",
            constraint=models.UniqueConstraint(
                condition=~Q(external_id=""),
                fields=("tenant", "external_id"),
                name="uniq_bank_revenue_tenant_external_id",
            ),
        ),
    ]
