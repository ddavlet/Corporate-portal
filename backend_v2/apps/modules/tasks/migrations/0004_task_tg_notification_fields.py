from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0003_task_source_expense_type_maxlength"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="tg_notify_message_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="tg_notify_recipient_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
