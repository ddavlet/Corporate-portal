from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants", "0025_tenant_create_payment_request_on_payroll_accrual"),
    ]

    operations = [
        migrations.CreateModel(
            name="McpServiceCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key_prefix", models.CharField(db_index=True, max_length=16, unique=True)),
                ("key_hash", models.CharField(max_length=255)),
                ("name", models.CharField(max_length=255)),
                (
                    "service_user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mcp_service_credential",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenants",
                    models.ManyToManyField(
                        blank=True,
                        related_name="mcp_service_credentials",
                        to="tenants.tenant",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "mcp_service_credential"},
        ),
    ]
