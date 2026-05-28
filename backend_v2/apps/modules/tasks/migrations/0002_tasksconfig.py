import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0001_initial"),
        ("tenants", "__first__"),
    ]

    operations = [
        migrations.CreateModel(
            name="TasksConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tasks_webapp_url", models.TextField(blank=True, default="", help_text="Telegram WebApp URL opened when user taps the digest button. Leave blank to omit button.")),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tasks_config",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"db_table": "tasks_config"},
        ),
    ]
