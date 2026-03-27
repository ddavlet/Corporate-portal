from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_user_swappable_option"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(
                error_messages={"unique": "A user with that username already exists."},
                help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.",
                max_length=150,
                unique=True,
                verbose_name="username",
            ),
        ),
    ]

