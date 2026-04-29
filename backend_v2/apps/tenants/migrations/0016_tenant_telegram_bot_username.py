from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0015_tenantuserrole_add_investor_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="telegram_bot_username",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
