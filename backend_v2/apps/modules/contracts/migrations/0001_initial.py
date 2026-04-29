from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

import apps.modules.contracts.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0001_initial"),
        ("vendors", "0012_drop_legacy_vendor_inn_transfer_unique_constraint"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Contract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contract_number", models.CharField(max_length=100)),
                ("date_from", models.DateField()),
                ("date_to", models.DateField(blank=True, null=True)),
                (
                    "contract_amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=18,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        choices=[
                            ("UZS", "UZS"),
                            ("USD", "USD"),
                            ("EUR", "EUR"),
                            ("RUB", "RUB"),
                        ],
                        default="UZS",
                        max_length=10,
                    ),
                ),
                (
                    "contract_status",
                    models.CharField(
                        choices=[("accepted", "Принят"), ("refused", "Отказан")],
                        default="accepted",
                        max_length=20,
                    ),
                ),
                ("contract_terms", models.TextField(blank=True, default="")),
                (
                    "contract_file",
                    models.FileField(
                        blank=True,
                        max_length=500,
                        null=True,
                        upload_to=apps.modules.contracts.models.contract_upload_to,
                    ),
                ),
                ("acc_number", models.CharField(blank=True, default="", max_length=100)),
                ("created_at", models.DateTimeField(default=timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_contracts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contracts",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "vendor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contracts",
                        to="vendors.vendor",
                    ),
                ),
            ],
            options={
                "db_table": "contracts",
            },
        ),
        migrations.AddConstraint(
            model_name="contract",
            constraint=models.UniqueConstraint(
                fields=("tenant", "vendor", "contract_number", "date_from"),
                name="contracts_tenant_vendor_number_date_from_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="contract",
            index=models.Index(fields=["tenant", "vendor"], name="contracts_tenant_vendor_idx"),
        ),
        migrations.AddIndex(
            model_name="contract",
            index=models.Index(fields=["tenant", "contract_status"], name="contracts_tenant_status_idx"),
        ),
    ]
