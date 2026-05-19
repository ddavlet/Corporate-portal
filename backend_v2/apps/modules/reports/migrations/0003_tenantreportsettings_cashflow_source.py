from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0002_tenantreportsettings_pnl_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantreportsettings",
            name="cashflow_source",
            field=models.CharField(
                choices=[("n8n", "n8n"), ("backend", "backend")],
                default="n8n",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="tenantreportsettings",
            name="cashflow_config",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
