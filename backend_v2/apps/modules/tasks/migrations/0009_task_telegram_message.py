from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0008_task_model_cleanup"),
        ("telegram_approvals", "0002_telegram_message"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="telegram_message",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="task",
                to="telegram_approvals.telegrammessage",
            ),
        ),
    ]
