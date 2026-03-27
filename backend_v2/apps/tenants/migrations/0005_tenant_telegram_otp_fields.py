from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0004_remove_usermodulepermission_and_membership_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="telegram_bot_token_enc",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenant",
            name="telegram_otp_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
