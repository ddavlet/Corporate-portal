from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_meta_options"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "verbose_name": "user",
                "verbose_name_plural": "users",
                "swappable": "AUTH_USER_MODEL",
            },
        ),
    ]

