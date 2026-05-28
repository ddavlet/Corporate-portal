from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0005_task_last_edit_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="task",
            name="source_expense_type",
        ),
        migrations.RemoveField(
            model_name="task",
            name="source_expense_id",
        ),
    ]
