from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0016_tenant_telegram_bot_username"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_oidc_client_id",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_oidc_client_secret_enc",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_oidc_redirect_uri",
            field=models.TextField(blank=True, default=""),
        ),
    ]
