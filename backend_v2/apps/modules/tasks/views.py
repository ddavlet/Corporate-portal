from __future__ import annotations

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.modules.tasks.models import Task
from apps.modules.tasks.permissions import (
    CanChangeStatus,
    CanCommentOnTask,
    CanDeleteTask,
    CanEditTask,
    CanRemindTask,
    CanViewTask,
    _is_tenant_admin_or_director,
    tenant_admin_director_user_ids,
)
from apps.modules.tasks.querysets.resolver import resolve_scope_for_user
from apps.modules.tasks.serializers import (
    DashboardSerializer,
    TaskCommentCreateSerializer,
    TaskCommentSerializer,
    TaskCreateSerializer,
    TaskDetailSerializer,
    TaskListSerializer,
    TaskPatchSerializer,
    TaskStatusChangeSerializer,
)
from apps.modules.tasks.services import task_service

logger = logging.getLogger(__name__)

# Serializer selected per ViewSet action — OCP: adding a new action adds one entry here.
_SERIALIZER_MAP: dict[str, type] = {
    "list": TaskListSerializer,
    "retrieve": TaskDetailSerializer,
    "create": TaskCreateSerializer,
    "partial_update": TaskPatchSerializer,
    "change_status": TaskStatusChangeSerializer,
    "add_comment": TaskCommentCreateSerializer,
    "dashboard": DashboardSerializer,
}


class TaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, CanViewTask]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    pagination_class = None

    # ------------------------------------------------------------------
    # Queryset
    # ------------------------------------------------------------------

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Task.objects.none()

        scope = resolve_scope_for_user(self.request.user, tenant)
        qs = scope.filter_queryset(
            Task.objects.filter(tenant=tenant).select_related(
                "assignee", "created_by", "tenant",
            ).prefetch_related("comments__author"),
            self.request.user,
            tenant,
        )

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        assignee_filter = self.request.query_params.get("assignee")
        if assignee_filter:
            qs = qs.filter(assignee_id=assignee_filter)

        # Archive of done tasks should be ordered by completion time, not creation.
        # The include_all_done flag controls whether we cap to "last 3" (done in the
        # dashboard endpoint); ordering is the same either way.
        if status_filter == Task.STATUS_DONE:
            qs = qs.order_by("-completed_at")

        return qs

    # ------------------------------------------------------------------
    # Serializer selection (OCP: extend _SERIALIZER_MAP, not this method)
    # ------------------------------------------------------------------

    def get_serializer_class(self):
        return _SERIALIZER_MAP.get(self.action, TaskListSerializer)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # Precompute admin/director user IDs once per request so comment serializers
        # do not issue per-comment role lookups (N+1 elimination).
        tenant = getattr(self.request, "tenant", None)
        ctx["admin_user_ids"] = tenant_admin_director_user_ids(tenant)
        return ctx

    # ------------------------------------------------------------------
    # Object lookup — scope filter applies to list only; detail uses full
    # tenant queryset so permission classes can return 403 (not 404) when
    # a user tries to access a task they don't own.
    # ------------------------------------------------------------------

    def get_object(self):
        from django.shortcuts import get_object_or_404
        from rest_framework.exceptions import NotFound

        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            raise NotFound()
        qs = (
            Task.objects.filter(tenant=tenant)
            .select_related("assignee", "created_by", "tenant")
            .prefetch_related("comments__author")
        )
        obj = get_object_or_404(qs, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, obj)
        return obj

    # ------------------------------------------------------------------
    # Standard actions
    # ------------------------------------------------------------------

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        task_service.mark_task_seen(task=instance, user=request.user)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        out = TaskDetailSerializer(task, context=self.get_serializer_context())
        return Response(out.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        # get_object() already calls check_object_permissions — no need to repeat.
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        out = TaskDetailSerializer(task, context=self.get_serializer_context())
        return Response(out.data)

    # ------------------------------------------------------------------
    # Custom actions
    # ------------------------------------------------------------------

    def get_permissions(self):
        """Attach the right object-level permission per action — OCP-style."""
        if self.action == "change_status":
            return [IsAuthenticated(), CanChangeStatus()]
        if self.action == "add_comment":
            return [IsAuthenticated(), CanCommentOnTask()]
        if self.action == "partial_update":
            return [IsAuthenticated(), CanEditTask()]
        if self.action == "destroy":
            return [IsAuthenticated(), CanDeleteTask()]
        if self.action == "remind":
            return [IsAuthenticated(), CanRemindTask()]
        return super().get_permissions()

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        # get_object() runs CanChangeStatus.has_object_permission via get_permissions().
        task = self.get_object()
        serializer = TaskStatusChangeSerializer(
            task, data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        out = TaskDetailSerializer(updated, context=self.get_serializer_context())
        return Response(out.data)

    @action(detail=True, methods=["post"], url_path="comments")
    def add_comment(self, request, pk=None):
        # get_object() runs CanCommentOnTask.has_object_permission via get_permissions().
        task = self.get_object()
        ctx = self.get_serializer_context()
        ctx["task"] = task
        serializer = TaskCommentCreateSerializer(data=request.data, context=ctx)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save()
        out = TaskCommentSerializer(comment, context=ctx)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"new": [], "in_progress": [], "done_recent": []})

        data = task_service.get_user_dashboard(user=request.user, tenant=tenant)
        serializer = DashboardSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["get", "patch"], url_path="config")
    def config(self, request):
        from apps.modules.tasks.models import TasksConfig
        from apps.modules.tasks.permissions import _is_tenant_admin_or_director

        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"tasks_webapp_url": ""})

        if request.method == "PATCH":
            if not _is_tenant_admin_or_director(request.user, tenant):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied()
            url = str(request.data.get("tasks_webapp_url", "") or "").strip()
            if url:
                from django.core.validators import URLValidator
                from django.core.exceptions import ValidationError as DjangoValidationError
                from rest_framework.exceptions import ValidationError as DRFValidationError
                try:
                    URLValidator()(url)
                except DjangoValidationError:
                    raise DRFValidationError(
                        {"tasks_webapp_url": "Введите корректный URL (например: https://t.me/mybot/tasks)."}
                    )
            # update_or_create handles the OneToOne race more gracefully than the
            # get_or_create + save pattern, which can hit IntegrityError under
            # simultaneous PATCH requests.
            cfg, _ = TasksConfig.objects.update_or_create(
                tenant=tenant,
                defaults={"tasks_webapp_url": url},
            )
            return Response({"tasks_webapp_url": cfg.tasks_webapp_url})

        cfg = TasksConfig.objects.filter(tenant=tenant).first()
        return Response({"tasks_webapp_url": (cfg.tasks_webapp_url if cfg else "") or ""})

    @action(detail=True, methods=["post"], url_path="remind")
    def remind(self, request, pk=None):
        task = self.get_object()
        try:
            from apps.modules.tasks.notifications.task_notifier import send_task_notification
            from apps.modules.telegram_approvals.services import get_tenant_bot_token
            tenant = getattr(request, "tenant", None)
            bot_token = get_tenant_bot_token(tenant)
            if bot_token:
                send_task_notification(task=task, tenant=tenant, bot_token=bot_token, is_reminder=True)
        except Exception:
            logger.exception("remind: failed to send reminder task_id=%s", task.pk)
        out = TaskDetailSerializer(task, context=self.get_serializer_context())
        return Response(out.data)

    @action(detail=False, methods=["get"], url_path="assignee-candidates")
    def assignee_candidates(self, request):
        from django.contrib.auth import get_user_model
        from apps.tenants.models import TenantMembership

        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response([])

        # Non-admin/director users can only assign tasks to themselves.
        if not _is_tenant_admin_or_director(request.user, tenant):
            return Response([{"id": request.user.id, "username": request.user.username}])

        User = get_user_model()
        active_ids = TenantMembership.objects.filter(
            tenant=tenant, is_active=True
        ).values_list("user_id", flat=True)
        users = User.objects.filter(id__in=active_ids).order_by("username")
        return Response([{"id": u.id, "username": u.username} for u in users])
