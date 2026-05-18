from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0020_tenant_cash_expense_external_id_format"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="request_ai_chat_webhook_url",
            field=models.TextField(blank=True, default=""),
        ),
    ]
