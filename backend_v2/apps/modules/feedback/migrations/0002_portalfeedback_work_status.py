import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feedback", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="portalfeedback",
            name="work_status",
            field=models.CharField(
                choices=[
                    ("new", "Новая"),
                    ("in_progress", "В работе"),
                    ("done", "Готово"),
                ],
                default="new",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="portalfeedback",
            name="assignee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_portal_feedbacks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="portalfeedback",
            name="resolution_note",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="portalfeedback",
            name="resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="portalfeedback",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name="portalfeedback",
            index=models.Index(
                fields=["work_status", "created_at"],
                name="portal_fb_work_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="portalfeedback",
            index=models.Index(
                fields=["assignee", "work_status"],
                name="portal_fb_assignee_work_idx",
            ),
        ),
    ]
