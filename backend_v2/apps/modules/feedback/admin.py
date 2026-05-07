from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from apps.modules.feedback.models import PortalFeedback


_WORK_STATUS_COLORS = {
    PortalFeedback.WORK_NEW: "#fa541c",        # red-orange
    PortalFeedback.WORK_IN_PROGRESS: "#1677ff",  # blue
    PortalFeedback.WORK_DONE: "#52c41a",       # green
}


@admin.register(PortalFeedback)
class PortalFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "tenant",
        "sender",
        "kind",
        "body_excerpt",
        "work_status_badge",
        "assignee",
        "delivery_status",
    )
    list_filter = (
        "work_status",
        "kind",
        "tenant",
        "assignee",
        "delivery_status",
    )
    search_fields = (
        "body",
        "page_path",
        "created_by__username",
        "created_by__full_name",
        "created_by__email",
    )
    list_editable = ("assignee",)
    autocomplete_fields = ("assignee", "tenant", "created_by")
    actions = ("assign_to_me", "mark_in_progress", "mark_done")
    list_select_related = ("tenant", "created_by", "assignee")
    ordering = ("-created_at",)

    fieldsets = (
        (
            "Обращение",
            {
                "fields": (
                    "tenant",
                    "created_by",
                    "kind",
                    "body",
                    "page_path",
                    "created_at",
                ),
            },
        ),
        (
            "Работа над обращением",
            {
                "fields": (
                    "work_status",
                    "assignee",
                    "resolution_note",
                    "resolved_at",
                    "updated_at",
                ),
            },
        ),
        (
            "Доставка в Telegram",
            {
                "fields": (
                    "delivery_status",
                    "delivery_error",
                    "sent_at",
                ),
            },
        ),
    )
    readonly_fields = (
        "tenant",
        "created_by",
        "kind",
        "body",
        "page_path",
        "created_at",
        "updated_at",
        "resolved_at",
        "delivery_status",
        "delivery_error",
        "sent_at",
    )

    @admin.display(description="Отправитель", ordering="created_by__username")
    def sender(self, obj):
        u = obj.created_by
        if not u:
            return "—"
        name = (getattr(u, "full_name", "") or "").strip()
        return f"{name} ({u.username})" if name else u.username

    @admin.display(description="Текст")
    def body_excerpt(self, obj):
        text = (obj.body or "").strip().replace("\n", " ")
        return text[:80] + ("…" if len(text) > 80 else "")

    @admin.display(description="Статус", ordering="work_status")
    def work_status_badge(self, obj):
        color = _WORK_STATUS_COLORS.get(obj.work_status, "#8c8c8c")
        label = obj.get_work_status_display()
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
            'background:{};color:#fff;font-weight:600;font-size:12px;">{}</span>',
            color,
            label,
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("tenant", "created_by", "assignee")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assignee":
            from django.contrib.auth import get_user_model

            User = get_user_model()
            kwargs["queryset"] = User.objects.filter(is_staff=True).order_by(
                "username"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.work_status == PortalFeedback.WORK_DONE and obj.resolved_at is None:
            obj.resolved_at = timezone.now()
        elif obj.work_status != PortalFeedback.WORK_DONE and obj.resolved_at is not None:
            obj.resolved_at = None
        super().save_model(request, obj, form, change)

    @admin.action(description="Назначить себя ответственным")
    def assign_to_me(self, request, queryset):
        if not request.user.is_staff:
            self.message_user(request, "Только сотрудники могут брать обращения в работу.", level="error")
            return
        now = timezone.now()
        updated = queryset.filter(assignee__isnull=True).update(
            assignee=request.user,
            work_status=PortalFeedback.WORK_IN_PROGRESS,
            updated_at=now,
        )
        skipped = queryset.count() - updated
        if updated:
            self.message_user(request, f"Назначено: {updated}.")
        if skipped:
            self.message_user(
                request,
                f"Пропущено (уже назначены): {skipped}. Чтобы переназначить — откройте запись.",
                level="warning",
            )

    @admin.action(description="Отметить «В работе»")
    def mark_in_progress(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(
            work_status=PortalFeedback.WORK_IN_PROGRESS,
            resolved_at=None,
            updated_at=now,
        )
        self.message_user(request, f"Обновлено: {updated}.")

    @admin.action(description="Отметить «Готово»")
    def mark_done(self, request, queryset):
        now = timezone.now()
        updated = 0
        for fb in queryset:
            fb.work_status = PortalFeedback.WORK_DONE
            if fb.resolved_at is None:
                fb.resolved_at = now
            fb.save(update_fields=["work_status", "resolved_at", "updated_at"])
            updated += 1
        self.message_user(request, f"Обновлено: {updated}.")
