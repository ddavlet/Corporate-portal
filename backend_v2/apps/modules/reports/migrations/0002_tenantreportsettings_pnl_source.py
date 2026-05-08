from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantreportsettings",
            name="pnl_source",
            field=models.CharField(
                choices=[("n8n", "n8n"), ("backend", "backend")],
                default="n8n",
                max_length=16,
            ),
        ),
    ]
