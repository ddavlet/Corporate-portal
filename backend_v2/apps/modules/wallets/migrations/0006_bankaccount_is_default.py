from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0005_drop_redundant_tenant_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="is_default",
            field=models.BooleanField(default=False),
        ),
        migrations.RemoveConstraint(
            model_name="bankaccount",
            name="wallets_bankaccount_one_per_tenant",
        ),
        migrations.AddConstraint(
            model_name="bankaccount",
            constraint=models.UniqueConstraint(
                fields=("tenant", "account_no", "mfo"), name="wallets_bankaccount_unique_per_account"
            ),
        ),
        migrations.AddConstraint(
            model_name="bankaccount",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_default", True)),
                fields=("tenant",),
                name="wallets_bankaccount_one_default_per_tenant",
            ),
        ),
    ]
