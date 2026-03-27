from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cashier", "0004_cash_expense_schema_rework"),
    ]

    operations = [
        migrations.AddField(
            model_name="cashexpense",
            name="confirmed",
            field=models.BooleanField(default=True),
        ),
    ]
