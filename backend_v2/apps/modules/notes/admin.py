from django.contrib import admin

from apps.modules.notes.models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "target_type",
        "target_id",
        "created_by",
        "recipient_user",
        "delivery_status",
        "created_at",
    )
    list_filter = ("tenant", "target_type", "delivery_status")
    search_fields = ("message", "created_by__username", "recipient_user__username")
