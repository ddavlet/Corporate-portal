from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_card", "0006_drop_cardrevenue_duplicate_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardexpense",
            name="external_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AlterField(
            model_name="cardrevenue",
            name="external_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddConstraint(
            model_name="cardexpense",
            constraint=models.UniqueConstraint(
                condition=~Q(external_id=""),
                fields=("tenant", "external_id"),
                name="uniq_card_expense_tenant_external_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="cardrevenue",
            constraint=models.UniqueConstraint(
                condition=~Q(external_id=""),
                fields=("tenant", "external_id"),
                name="uniq_card_revenue_tenant_external_id",
            ),
        ),
    ]
