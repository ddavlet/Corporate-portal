from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class Task(models.Model):
    STATUS_NEW = "new"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_DONE, "Done"),
    ]

    SOURCE_APPROVAL_STEP = "approval_step"
    SOURCE_REQUEST_APPROVED = "request_approved"
    SOURCE_PAYMENT_VERIFY = "payment_verify"
    SOURCE_REQUEST_REJECTED = "request_rejected"
    SOURCE_ESCALATION = "escalation"
    SOURCE_MANUAL = "manual"

    SOURCE_TYPE_CHOICES = [
        (SOURCE_APPROVAL_STEP, "Approval Step"),
        (SOURCE_REQUEST_APPROVED, "Request Approved"),
        (SOURCE_PAYMENT_VERIFY, "Payment Verify"),
        (SOURCE_REQUEST_REJECTED, "Request Rejected"),
        (SOURCE_ESCALATION, "Escalation"),
        (SOURCE_MANUAL, "Manual"),
    ]

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
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
    )
    source_type = models.CharField(
        max_length=32,
        choices=SOURCE_TYPE_CHOICES,
        default=SOURCE_MANUAL,
        blank=True,
    )
    source_approval = models.ForeignKey(
        "requests.Approval",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    source_request = models.ForeignKey(
        "requests.Request",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    source_expense_type = models.CharField(max_length=32, blank=True, default="")
    source_expense_id = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    last_admin_comment_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tasks"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "assignee", "status"], name="task_asgn_status_idx"),
            models.Index(fields=["tenant", "status", "completed_at"], name="task_tenant_status_done_idx"),
            models.Index(fields=["source_approval"], name="task_source_approval_idx"),
            models.Index(fields=["source_request"], name="task_source_request_idx"),
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
