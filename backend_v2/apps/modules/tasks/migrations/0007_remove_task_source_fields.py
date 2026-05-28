from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0006_remove_task_expense_fields"),
        ("requests", "0001_initial"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="task",
            name="task_source_approval_idx",
        ),
        migrations.RemoveIndex(
            model_name="task",
            name="task_source_request_idx",
        ),
        migrations.RemoveField(
            model_name="task",
            name="source_type",
        ),
        migrations.RemoveField(
            model_name="task",
            name="source_approval",
        ),
        migrations.RemoveField(
            model_name="task",
            name="source_request",
        ),
    ]
