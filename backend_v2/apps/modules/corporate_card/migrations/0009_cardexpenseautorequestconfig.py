# Hand-written: per-card settings for automatic «Платежная карта» requests from card expenses

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_card", "0008_drop_redundant_tenant_indexes"),
        ("wallets", "0007_bankaccount_account_type"),
        ("vendors", "0013_drop_redundant_tenant_index"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CardExpenseAutoRequestConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False)),
                ("payment_purpose", models.CharField(blank=True, default="", max_length=200)),
                ("category", models.CharField(blank=True, default="", max_length=100)),
                ("company_payer", models.CharField(blank=True, default="", max_length=100)),
                ("match_text", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="card_expense_auto_request_configs",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "wallet",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="card_auto_request_config",
                        to="wallets.wallet",
                    ),
                ),
                (
                    "vendor_ref",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="card_expense_auto_request_configs",
                        to="vendors.vendor",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="updated_card_expense_auto_request_configs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "corporate_card_auto_request_configs",
                "indexes": [
                    models.Index(fields=["tenant", "is_enabled"], name="corp_card_autoreq_tnt_en_idx"),
                ],
            },
        ),
    ]
