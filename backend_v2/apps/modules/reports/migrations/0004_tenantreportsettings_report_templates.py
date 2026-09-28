import apps.modules.reports.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0003_tenantreportsettings_cashflow_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantreportsettings",
            name="allowed_templates",
            field=models.JSONField(
                blank=True,
                default=apps.modules.reports.models.default_allowed_templates,
            ),
        ),
        migrations.AddField(
            model_name="tenantreportsettings",
            name="default_template",
            field=models.CharField(default="classic", max_length=32),
        ),
    ]
