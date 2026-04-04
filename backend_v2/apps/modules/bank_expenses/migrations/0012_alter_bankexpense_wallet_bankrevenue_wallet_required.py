import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bank_expenses", "0011_bankexpense_wallet_bankrevenue_wallet"),
        ("wallets", "0002_backfill_movement_wallets"),
    ]

    operations = [
        migrations.AlterField(
            model_name="bankexpense",
            name="wallet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bank_expenses",
                to="wallets.wallet",
            ),
        ),
        migrations.AlterField(
            model_name="bankrevenue",
            name="wallet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bank_revenues",
                to="wallets.wallet",
            ),
        ),
    ]
