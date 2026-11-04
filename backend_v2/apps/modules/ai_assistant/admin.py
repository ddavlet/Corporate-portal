from django.contrib import admin

from apps.common.admin_labels import set_portal_labels
from apps.modules.ai_assistant.models import ChainNode, PendingConfirmation, UsageRecord


@admin.register(ChainNode)
class ChainNodeAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "chat_id", "message_id", "parent_message_id", "kind", "author_label", "created_at")
    list_filter = ("tenant", "kind")
    search_fields = ("chat_id", "author_label", "text")
    raw_id_fields = ("tenant", "author_user")
    readonly_fields = ("created_at",)


@admin.register(PendingConfirmation)
class PendingConfirmationAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "chat_id", "requester_user", "status", "created_at", "expires_at", "resolved_at")
    list_filter = ("tenant", "status")
    search_fields = ("chat_id",)
    raw_id_fields = ("tenant", "requester_user", "confirmation_message")


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "user", "model", "outcome", "input_tokens", "output_tokens", "cost_usd", "created_at")
    list_filter = ("tenant", "model", "outcome")
    raw_id_fields = ("tenant", "user")


set_portal_labels(ChainNode, "Узел цепочки AI", "Узлы цепочек AI")
set_portal_labels(PendingConfirmation, "Подтверждение AI", "Подтверждения AI")
set_portal_labels(UsageRecord, "Расход AI", "Расходы AI")
