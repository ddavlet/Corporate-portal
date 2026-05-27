from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.modules.tasks.models import Task, TaskComment
from apps.modules.tasks.permissions import _is_tenant_admin_or_director, tenant_admin_director_user_ids

User = get_user_model()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _send_new_task_notification(*, task, tenant) -> None:
    """Fire-and-forget: send Telegram notification for a newly created task."""
    try:
        from apps.modules.tasks.notifications.task_notifier import send_task_notification
        from apps.modules.telegram_approvals.services import get_tenant_bot_token
        bot_token = get_tenant_bot_token(tenant)
        if bot_token:
            send_task_notification(task=task, tenant=tenant, bot_token=bot_token)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Failed to send new-task notification task_id=%s", getattr(task, "pk", None)
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _user_dict(user) -> dict | None:
    if not user:
        return None
    return {"id": user.id, "username": user.username}


# ---------------------------------------------------------------------------
# Comment serializers
# ---------------------------------------------------------------------------

class TaskCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    is_admin_comment = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = ("id", "author", "body", "created_at", "is_admin_comment")
        read_only_fields = fields

    def get_author(self, obj) -> dict | None:
        return _user_dict(obj.author)

    def get_is_admin_comment(self, obj) -> bool:
        if not obj.author_id or obj.author_id == obj.task.assignee_id:
            return False
        # Prefer the precomputed set from context (set once per request) — avoids N+1
        # role lookups when serializing a task with many comments.
        admin_ids = self.context.get("admin_user_ids")
        if admin_ids is not None:
            return obj.author_id in admin_ids
        tenant = getattr(obj.task, "tenant", None)
        if not tenant:
            return False
        return _is_tenant_admin_or_director(obj.author, tenant)


class TaskCommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(min_length=1, trim_whitespace=True)

    def create(self, validated_data):
        from apps.modules.tasks.services import comment_service
        task = self.context["task"]
        author = self.context["request"].user
        try:
            return comment_service.add_comment(
                task=task,
                author=author,
                body=validated_data["body"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message)


# ---------------------------------------------------------------------------
# Task list serializer (used by GET /tasks/)
# ---------------------------------------------------------------------------

class TaskListSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()
    has_unseen_admin_comment = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            "id",
            "title",
            "status",
            "source_type",
            "assignee",
            "created_by_id",
            "source_request_id",
            "source_approval_id",
            "created_at",
            "completed_at",
            "has_unseen_admin_comment",
        )
        read_only_fields = fields

    def get_assignee(self, obj) -> dict | None:
        return _user_dict(obj.assignee)

    def get_has_unseen_admin_comment(self, obj) -> bool:
        if not obj.last_admin_comment_at:
            return False
        if not obj.last_seen_at:
            return True
        return obj.last_seen_at < obj.last_admin_comment_at


# ---------------------------------------------------------------------------
# Task detail serializer (used by GET /tasks/{id}/)
# ---------------------------------------------------------------------------

class TaskDetailSerializer(TaskListSerializer):
    created_by = serializers.SerializerMethodField()
    comments = TaskCommentSerializer(many=True, read_only=True)

    class Meta(TaskListSerializer.Meta):
        fields = TaskListSerializer.Meta.fields + (
            "description",
            "created_by",
            "updated_at",
            "source_expense_type",
            "source_expense_id",
            "comments",
        )
        read_only_fields = fields

    def get_created_by(self, obj) -> dict | None:
        return _user_dict(obj.created_by)


# ---------------------------------------------------------------------------
# Task create serializer (used by POST /tasks/)
# ---------------------------------------------------------------------------

class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, min_length=1, trim_whitespace=True)
    description = serializers.CharField(required=False, default="", allow_blank=True, trim_whitespace=True)
    assignee_id = serializers.IntegerField()
    source_request_id = serializers.IntegerField(required=False, allow_null=True)
    notify = serializers.BooleanField(default=False, write_only=True)

    def _request_tenant(self):
        request = self.context.get("request")
        return getattr(request, "tenant", None) if request else None

    def validate_assignee_id(self, value):
        from apps.tenants.models import TenantMembership
        tenant = self._request_tenant()
        if tenant is None:
            raise serializers.ValidationError("Tenant context is required.")
        if not TenantMembership.objects.filter(
            tenant=tenant, user_id=value, is_active=True
        ).exists():
            raise serializers.ValidationError("Assignee is not a member of this tenant.")
        return value

    def validate_source_request_id(self, value):
        if value is None:
            return value
        from apps.modules.requests.models import Request
        tenant = self._request_tenant()
        if tenant is None:
            raise serializers.ValidationError("Tenant context is required.")
        if not Request.objects.filter(id=value, tenant=tenant).exists():
            raise serializers.ValidationError("Source request not found in this tenant.")
        return value

    def validate(self, data):
        from apps.modules.tasks.permissions import _is_tenant_admin_or_director
        request = self.context.get("request")
        user = request.user if request else None
        tenant = self._request_tenant()
        # Non-admin/director users can only create tasks for themselves.
        if user and not _is_tenant_admin_or_director(user, tenant):
            if data.get("assignee_id") != user.id:
                raise serializers.ValidationError(
                    {"assignee_id": "You can only create tasks assigned to yourself."}
                )
        return data

    def create(self, validated_data):
        from apps.modules.tasks.services import task_service
        from apps.modules.requests.models import Request

        request = self.context["request"]
        tenant = request.tenant
        actor = request.user
        notify = validated_data.pop("notify", False)

        assignee = User.objects.get(id=validated_data["assignee_id"])
        source_request = None
        if validated_data.get("source_request_id"):
            source_request = Request.objects.get(id=validated_data["source_request_id"])

        task = task_service.create_task(
            tenant=tenant,
            assignee=assignee,
            title=validated_data["title"],
            description=validated_data.get("description", ""),
            created_by=actor,
            source_type=Task.SOURCE_MANUAL,
            source_request=source_request,
        )

        if notify:
            _send_new_task_notification(task=task, tenant=tenant)

        return task


# ---------------------------------------------------------------------------
# Task patch serializer (used by PATCH /tasks/{id}/)
# ---------------------------------------------------------------------------

class TaskPatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ("title", "description")

    def update(self, instance, validated_data):
        instance.title = validated_data.get("title", instance.title)
        instance.description = validated_data.get("description", instance.description)
        instance.save(update_fields=["title", "description", "updated_at"])
        return instance


# ---------------------------------------------------------------------------
# Status change serializer (used by POST /tasks/{id}/status/)
# ---------------------------------------------------------------------------

class TaskStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Task.STATUS_CHOICES)

    def update(self, instance, validated_data):
        from apps.modules.tasks.services import task_service
        try:
            return task_service.set_status(
                task=instance,
                new_status=validated_data["status"],
                actor=self.context["request"].user,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"status": exc.message})


# ---------------------------------------------------------------------------
# Dashboard serializer (used by GET /tasks/dashboard/)
# ---------------------------------------------------------------------------

class DashboardSerializer(serializers.Serializer):
    new = TaskListSerializer(many=True, read_only=True)
    in_progress = TaskListSerializer(many=True, read_only=True)
    done_recent = TaskListSerializer(many=True, read_only=True)
