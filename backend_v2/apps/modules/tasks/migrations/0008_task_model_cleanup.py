import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0007_remove_task_source_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name="task",
            name="last_admin_comment_at",
        ),
        migrations.RemoveField(
            model_name="task",
            name="last_seen_at",
        ),
        migrations.RemoveField(
            model_name="task",
            name="tg_notify_message_id",
        ),
        migrations.RemoveField(
            model_name="task",
            name="tg_notify_recipient_id",
        ),
        migrations.AlterField(
            model_name="task",
            name="status",
            field=models.CharField(
                choices=[("new", "New"), ("in_progress", "In Progress"), ("done", "Done")],
                default="new",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="task",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="task",
            name="last_edit_at",
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name="task",
            name="last_edit_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="last_edited_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
