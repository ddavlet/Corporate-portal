import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cashier", "0007_cashexpense_wallet_cashrevenue_wallet"),
        ("wallets", "0002_backfill_movement_wallets"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cashexpense",
            name="wallet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cash_expenses",
                to="wallets.wallet",
            ),
        ),
        migrations.AlterField(
            model_name="cashrevenue",
            name="wallet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cash_revenues",
                to="wallets.wallet",
            ),
        ),
    ]
