from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mcp_oauth", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="oauthauthorizationcode",
            name="state",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="oauthauthorizationcode",
            name="code_challenge",
            field=models.TextField(),
        ),
    ]
