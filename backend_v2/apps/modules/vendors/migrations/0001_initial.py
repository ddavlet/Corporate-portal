from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0005_tenant_telegram_otp_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Vendor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("cash", "cash"), ("transfer", "transfer")], max_length=20)),
                ("name", models.CharField(max_length=255)),
                ("inn", models.CharField(blank=True, max_length=20, null=True, verbose_name="ИНН")),
                ("account_number", models.CharField(blank=True, max_length=34, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_directory_vendors",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vendor_directory",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "vendors_directory",
            },
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(
                fields=["tenant", "inn"],
                condition=Q(kind="transfer") & ~Q(inn="") & Q(inn__isnull=False),
                name="vendors_directory_tenant_inn_transfer_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(
                fields=["tenant", "name", "kind"],
                condition=Q(kind="cash"),
                name="vendors_directory_tenant_name_kind_cash_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="vendor",
            index=models.Index(fields=["tenant", "kind"], name="vendors_dir_tenant_kind_idx"),
        ),
        migrations.AddIndex(
            model_name="vendor",
            index=models.Index(fields=["tenant", "name"], name="vendors_dir_tenant_name_idx"),
        ),
    ]
