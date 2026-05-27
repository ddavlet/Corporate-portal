import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("requests", "__first__"),
        ("tenants", "__first__"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Task",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[("new", "New"), ("in_progress", "In Progress"), ("done", "Done")],
                        default="new",
                        max_length=16,
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("approval_step", "Approval Step"),
                            ("request_approved", "Request Approved"),
                            ("payment_verify", "Payment Verify"),
                            ("request_rejected", "Request Rejected"),
                            ("escalation", "Escalation"),
                            ("manual", "Manual"),
                        ],
                        default="manual",
                        max_length=32,
                    ),
                ),
                ("source_expense_type", models.CharField(blank=True, default="", max_length=8)),
                ("source_expense_id", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_admin_comment_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                (
                    "assignee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assigned_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source_approval",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tasks",
                        to="requests.approval",
                    ),
                ),
                (
                    "source_request",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tasks",
                        to="requests.request",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tasks",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "tasks",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="TaskComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="task_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="tasks.task",
                    ),
                ),
            ],
            options={
                "db_table": "task_comments",
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["tenant", "assignee", "status"],
                name="task_asgn_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["tenant", "status", "completed_at"],
                name="task_tenant_status_done_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["source_approval"],
                name="task_source_approval_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["source_request"],
                name="task_source_request_idx",
            ),
        ),
    ]
