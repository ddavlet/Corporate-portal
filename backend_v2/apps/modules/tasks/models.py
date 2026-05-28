from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class Task(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In Progress"
        DONE = "done", "Done"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_tasks",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tasks",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.NEW,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    last_edit_at = models.DateTimeField()
    last_edit_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="last_edited_tasks",
    )

    class Meta:
        db_table = "tasks"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "assignee", "status"], name="task_asgn_status_idx"),
            models.Index(fields=["tenant", "status", "completed_at"], name="task_tenant_status_done_idx"),
        ]

    def __str__(self):
        return f"[{self.status}] {self.title} → {self.assignee_id}"


class TasksConfig(models.Model):
    """Per-tenant configuration for the tasks module (e.g. Telegram webapp URL)."""

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="tasks_config",
    )
    tasks_webapp_url = models.TextField(
        blank=True,
        default="",
        help_text="Telegram WebApp URL opened when user taps the digest button. Leave blank to omit button.",
    )

    class Meta:
        db_table = "tasks_config"

    def __str__(self):
        return f"TasksConfig for {self.tenant_id}"


class TaskComment(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_comments",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "task_comments"
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author_id} on task {self.task_id}"
