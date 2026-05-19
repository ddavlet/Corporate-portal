from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0021_tenantintegrationconfig_request_ai_chat_webhook_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="mcp_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
