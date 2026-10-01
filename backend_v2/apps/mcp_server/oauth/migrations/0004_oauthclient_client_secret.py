from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mcp_oauth", "0003_oauthauthorizationcode_tenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthclient",
            name="client_secret",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="oauthclient",
            name="client_secret_expires_at",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
