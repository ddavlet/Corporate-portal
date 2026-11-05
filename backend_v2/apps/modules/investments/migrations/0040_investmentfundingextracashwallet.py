from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0039_projectinvestmentrequestlink"),
        ("wallets", "0007_bankaccount_account_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestmentFundingExtraCashWallet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "config",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="extra_cash_wallet_links",
                        to="investments.investmentfundingconfig",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="wallets.wallet",
                    ),
                ),
            ],
            options={
                "db_table": "investment_funding_extra_cash_wallets",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("config", "wallet"),
                        name="uniq_invest_funding_extra_cash_wallet",
                    )
                ],
            },
        ),
    ]
