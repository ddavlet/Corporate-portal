import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0006_bankaccount_is_default"),
        ("requests", "0063_userapprovalvacation"),
    ]

    operations = [
        migrations.AddField(
            model_name="request",
            name="wallet_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="requests",
                to="wallets.wallet",
            ),
        ),
    ]
