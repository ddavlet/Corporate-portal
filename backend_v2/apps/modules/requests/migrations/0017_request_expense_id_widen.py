from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0016_request_form_payment_type_defaults"),
    ]

    operations = [
        migrations.AlterField(
            model_name="request",
            name="expense_id",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
