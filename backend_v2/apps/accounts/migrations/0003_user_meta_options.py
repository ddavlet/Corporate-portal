from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_name_field"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
    ]

