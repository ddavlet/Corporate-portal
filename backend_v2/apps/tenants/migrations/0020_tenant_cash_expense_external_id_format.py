from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0019_remove_messaging_gateway_fields_from_tenant_integration"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="cash_expense_external_id_prefix",
            field=models.CharField(default="1-", max_length=32),
        ),
        migrations.AddField(
            model_name="tenant",
            name="cash_expense_external_id_digit_width",
            field=models.PositiveSmallIntegerField(default=9),
        ),
    ]
