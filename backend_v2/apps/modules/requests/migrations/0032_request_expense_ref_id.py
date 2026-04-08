from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0031_request_amortization_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="request",
            name="expense_ref_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
