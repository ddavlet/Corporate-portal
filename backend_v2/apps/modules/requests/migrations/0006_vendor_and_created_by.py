from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_name_field"),
        ("tenants", "0001_initial"),
        ("requests", "0005_request_choice_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="Vendor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("account_number", models.CharField(blank=True, max_length=34, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_vendors",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vendors",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "vendors",
            },
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(fields=("tenant", "name"), name="uniq_vendor_tenant_name"),
        ),
        migrations.AddField(
            model_name="request",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="request",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_requests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

