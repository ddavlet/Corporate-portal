from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0010_tenantintegrationconfig_draft_notification_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="portal_feedback_telegram_chat_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="portal_feedback_telegram_action",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
