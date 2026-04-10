from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cashier", "0012_remove_cashrevenue_account"),
    ]

    operations = [
        migrations.AddField(
            model_name="cashrevenue",
            name="source_year",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="cashrevenue",
            constraint=models.UniqueConstraint(
                fields=("tenant", "external_id", "source_year"),
                name="cash_rev_tenant_external_source_year_uniq",
            ),
        ),
    ]
