import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_card", "0003_cardexpense_wallet_cardrevenue_wallet"),
        ("wallets", "0002_backfill_movement_wallets"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cardexpense",
            name="wallet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="card_expenses",
                to="wallets.wallet",
            ),
        ),
        migrations.AlterField(
            model_name="cardrevenue",
            name="wallet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="card_revenues",
                to="wallets.wallet",
            ),
        ),
    ]
