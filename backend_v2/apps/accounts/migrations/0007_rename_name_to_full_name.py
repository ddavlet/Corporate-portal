from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_alter_user_username"),
    ]

    operations = [
        migrations.RenameField(
            model_name="user",
            old_name="name",
            new_name="full_name",
        ),
    ]

