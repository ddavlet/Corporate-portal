from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0006_tenantintegrationconfig"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_webhook_token_enc",
        ),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="notes_telegram_api_base_url",
        ),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="notes_target_path_request",
        ),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="notes_target_path_cash",
        ),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="notes_target_path_bank",
        ),
    ]

