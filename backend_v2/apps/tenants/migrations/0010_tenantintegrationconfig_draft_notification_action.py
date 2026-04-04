from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0009_tenantintegrationconfig_telegram_header_templates"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE tenant_integration_configs "
                        "ADD COLUMN IF NOT EXISTS telegram_approvals_draft_notification_action "
                        "varchar(100) DEFAULT '' NOT NULL;"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="tenantintegrationconfig",
                    name="telegram_approvals_draft_notification_action",
                    field=models.CharField(blank=True, default="", max_length=100),
                ),
            ],
        ),
    ]
