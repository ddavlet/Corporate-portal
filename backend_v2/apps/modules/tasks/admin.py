from django.contrib import admin

from apps.modules.tasks.models import Task, TaskComment, TasksConfig


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    readonly_fields = ("author", "body", "created_at")
    can_delete = False


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "assignee", "status", "created_at", "completed_at")
    list_filter = ("status", "tenant")
    search_fields = ("title", "description", "assignee__username")
    readonly_fields = ("created_at", "updated_at", "completed_at", "last_admin_comment_at", "last_seen_at", "last_edit_at", "last_edit_by")
    raw_id_fields = ("tenant", "assignee", "created_by", "last_edit_by")
    date_hierarchy = "created_at"
    inlines = [TaskCommentInline]


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "author", "created_at")
    search_fields = ("body", "author__username")
    raw_id_fields = ("task", "author")
    readonly_fields = ("created_at",)


@admin.register(TasksConfig)
class TasksConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "tasks_webapp_url")
    raw_id_fields = ("tenant",)
