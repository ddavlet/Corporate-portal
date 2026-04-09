from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0002_backfill_movement_wallets"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="cashregister",
            name="wallets_cashreg_tenant_currency_uniq",
        ),
        migrations.RemoveConstraint(
            model_name="corporatecardaccount",
            name="wallets_corpacct_tenant_currency_uniq",
        ),
    ]
