from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0036_remove_investreturn_sum_uzs"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
        ("wallets", "0006_bankaccount_is_default"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="projectinvestment",
            name="funding_method",
            field=models.CharField(
                blank=True,
                choices=[("cash", "Наличными"), ("bank_transfer", "Переводом на счёт")],
                max_length=16,
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="InvestmentFundingConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False)),
                ("enabled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "bank_wallet",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="wallets.wallet",
                    ),
                ),
                (
                    "cash_wallet",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="wallets.wallet",
                    ),
                ),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_funding_config",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "investment_funding_config",
            },
        ),
    ]
