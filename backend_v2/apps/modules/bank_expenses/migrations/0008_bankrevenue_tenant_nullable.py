import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0007_bankexpense_expense_calendar"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankrevenue",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="bank_revenues",
                to="tenants.tenant",
            ),
        ),
    ]
