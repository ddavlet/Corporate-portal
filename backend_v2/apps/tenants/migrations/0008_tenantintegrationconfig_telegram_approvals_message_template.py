from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0007_remove_extra_tenant_integration_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_message_template",
            field=models.TextField(blank=True, default=""),
        ),
    ]
