from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0003_drop_currency_uniqs"),
    ]

    operations = [
        migrations.AddField(
            model_name="wallet",
            name="is_visible_in_cash_section",
            field=models.BooleanField(default=True),
        ),
    ]
