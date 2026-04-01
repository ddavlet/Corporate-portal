from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0005_tenant_telegram_otp_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantIntegrationConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("telegram_approvals_bridge_dispatch_url", models.TextField(blank=True, default="")),
                ("telegram_approvals_send_action", models.CharField(blank=True, default="send_approval_message", max_length=100)),
                ("telegram_approvals_edit_action", models.CharField(blank=True, default="edit_approval_message", max_length=100)),
                ("telegram_approvals_bridge_token_enc", models.TextField(blank=True, default="")),
                ("telegram_approvals_webhook_token_enc", models.TextField(blank=True, default="")),
                ("n8n_integration_token_enc", models.TextField(blank=True, default="")),
                ("requests_file_gateway_token_enc", models.TextField(blank=True, default="")),
                ("notes_telegram_api_base_url", models.TextField(blank=True, default="https://api.telegram.org")),
                ("notes_target_path_request", models.CharField(blank=True, default="/app/requests/{id}", max_length=200)),
                ("notes_target_path_cash", models.CharField(blank=True, default="/app/cash/{id}", max_length=200)),
                ("notes_target_path_bank", models.CharField(blank=True, default="/app/bank/{id}", max_length=200)),
                (
                    "tenant",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="integration_config", to="tenants.tenant"),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="updated_tenant_integration_configs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "tenant_integration_configs"},
        ),
    ]

