from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.requests.models import (
    Approval,
    AutoRequestTemplate,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestApprovalPurposeExceptionStepApproverConfig,
    RequestApprovalPurposeExceptionStepConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestAttachment,
    RequestCategory,
    RequestComment,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestFormPaymentTypeVendor,
    RequestPaymentPurposeConfig,
    UserApprovalVacation,
)


class RequestAttachmentInline(admin.TabularInline):
    model = RequestAttachment
    extra = 0
    raw_id_fields = ("created_by", "tenant")


class ApprovalInline(admin.TabularInline):
    model = Approval
    extra = 0
    raw_id_fields = ("approver_user", "telegram_message", "replaced_approval")
    fields = ("step", "step_type", "approver_user", "decision", "comment", "decided_at")
    readonly_fields = ("decided_at",)


class RequestCommentInline(admin.TabularInline):
    model = RequestComment
    extra = 0
    raw_id_fields = ("created_by",)
    readonly_fields = ("created_at",)


class RequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "title",
        "status",
        "payment_type",
        "amount",
        "currency",
        "requester",
        "submitted_at",
    )
    list_filter = ("status", "payment_type", "tenant", "currency")
    search_fields = ("id", "title", "description", "vendor", "category", "expense_id")
    raw_id_fields = (
        "tenant",
        "created_by",
        "requester",
        "vendor_ref",
        "contract_ref",
        "source_tenant",
        "external_matched_tenant",
    )
    date_hierarchy = "submitted_at"
    inlines = [ApprovalInline, RequestAttachmentInline, RequestCommentInline]

    def get_queryset(self, request):
        return Request.all_objects.select_related("tenant", "created_by", "requester")


class ApprovalAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "step", "step_type", "approver_user", "decision", "decided_at")
    list_filter = ("decision", "step_type")
    raw_id_fields = ("request", "approver_user", "telegram_message", "replaced_approval")
    search_fields = ("request__id", "approver_user__username", "comment")


class RequestAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "request", "file_name", "size_bytes", "created_at")
    list_filter = ("tenant",)
    search_fields = ("file_name", "file_path")
    raw_id_fields = ("request", "tenant", "created_by")


class RequestCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "created_by", "created_at")
    search_fields = ("body", "created_by__username")
    raw_id_fields = ("request", "created_by")


class RequestCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "is_active")
    list_filter = ("tenant", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ("tenant",)


class RequestFormPaymentTypeRequesterInline(admin.TabularInline):
    model = RequestFormPaymentTypeRequester
    extra = 0
    raw_id_fields = ("user",)


class RequestFormPaymentTypeVendorInline(admin.TabularInline):
    model = RequestFormPaymentTypeVendor
    extra = 0
    raw_id_fields = ("vendor",)


class RequestPaymentPurposeInline(admin.TabularInline):
    model = RequestPaymentPurposeConfig
    extra = 0


class RequestFormPaymentTypeConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "config", "payment_type", "is_enabled")
    list_filter = ("payment_type", "is_enabled")
    raw_id_fields = ("config", "default_vendor")
    inlines = [
        RequestFormPaymentTypeRequesterInline,
        RequestFormPaymentTypeVendorInline,
        RequestPaymentPurposeInline,
    ]


class RequestFormPaymentTypeConfigInline(admin.TabularInline):
    model = RequestFormPaymentTypeConfig
    extra = 0
    show_change_link = True
    fields = ("payment_type", "is_enabled", "default_title", "contracts_required")


class RequestFormConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "updated_at", "updated_by")
    autocomplete_fields = ("tenant",)
    raw_id_fields = ("updated_by",)
    inlines = [RequestFormPaymentTypeConfigInline]


class RequestApprovalStepApproverInline(admin.TabularInline):
    model = RequestApprovalStepApproverConfig
    extra = 0
    raw_id_fields = ("approver_user",)


class RequestApprovalStepConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "payment_type_config", "step", "step_type", "is_enabled")
    list_filter = ("step_type", "is_enabled")
    raw_id_fields = ("payment_type_config", "telegram_chat")
    inlines = [RequestApprovalStepApproverInline]


class RequestApprovalStepConfigInline(admin.TabularInline):
    model = RequestApprovalStepConfig
    extra = 0
    show_change_link = True
    fields = ("step", "step_type", "is_enabled")


class RequestApprovalPaymentTypeConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "config", "payment_type", "is_enabled")
    list_filter = ("payment_type", "is_enabled")
    raw_id_fields = ("config",)
    inlines = [RequestApprovalStepConfigInline]


class RequestApprovalPaymentTypeConfigInline(admin.TabularInline):
    model = RequestApprovalPaymentTypeConfig
    extra = 0
    show_change_link = True
    fields = ("payment_type", "is_enabled")


class RequestApprovalConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "updated_at", "updated_by")
    autocomplete_fields = ("tenant",)
    raw_id_fields = ("updated_by",)
    inlines = [RequestApprovalPaymentTypeConfigInline]


class AutoRequestTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "payment_type", "is_enabled", "day_of_month", "last_run_month")
    list_filter = ("tenant", "is_enabled", "payment_type")
    search_fields = ("name", "title_template")
    raw_id_fields = ("tenant", "vendor_ref", "contract_ref", "requester", "updated_by")


class UserApprovalVacationAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "user", "started_at", "ended_at")
    list_filter = ("tenant",)
    raw_id_fields = ("tenant", "user")


register_portal(Request, "Заявка", "Заявки", RequestAdmin)
register_portal(Approval, "Согласование", "Согласования", ApprovalAdmin)
register_portal(RequestAttachment, "Вложение заявки", "Вложения заявок", RequestAttachmentAdmin)
register_portal(RequestComment, "Комментарий к заявке", "Комментарии к заявкам", RequestCommentAdmin)
register_portal(RequestCategory, "Категория заявки", "Категории заявок", RequestCategoryAdmin)
register_portal(RequestFormConfig, "Форма создания", "Форма создания", RequestFormConfigAdmin)
register_portal(
    RequestFormPaymentTypeConfig,
    "Тип оплаты (форма)",
    "Типы оплаты (форма)",
    RequestFormPaymentTypeConfigAdmin,
)
register_portal(
    RequestFormPaymentTypeRequester,
    "Заявитель типа оплаты",
    "Заявители типов оплаты",
    list_display=("id", "payment_type_config", "user"),
    raw_id_fields=("payment_type_config", "user"),
)
register_portal(
    RequestFormPaymentTypeVendor,
    "Поставщик типа оплаты",
    "Поставщики типов оплаты",
    list_display=("id", "payment_type_config", "vendor"),
    raw_id_fields=("payment_type_config", "vendor"),
)
register_portal(
    RequestPaymentPurposeConfig,
    "Назначение платежа",
    "Назначения платежа",
    list_display=("id", "payment_type_config", "name", "category", "is_active"),
    raw_id_fields=("payment_type_config",),
)
register_portal(RequestApprovalConfig, "Этапы согласования", "Этапы согласования", RequestApprovalConfigAdmin)
register_portal(
    RequestApprovalPaymentTypeConfig,
    "Тип оплаты (согласование)",
    "Типы оплаты (согласование)",
    RequestApprovalPaymentTypeConfigAdmin,
)
register_portal(RequestApprovalStepConfig, "Этап согласования", "Этапы согласования", RequestApprovalStepConfigAdmin)
register_portal(
    RequestApprovalStepApproverConfig,
    "Согласующий этапа",
    "Согласующие этапов",
    list_display=("id", "step_config", "approver_user"),
    raw_id_fields=("step_config", "approver_user"),
)
register_portal(
    RequestApprovalPurposeExceptionConfig,
    "Исключение по назначению",
    "Исключения по назначению",
    list_display=("id", "payment_type_config", "name", "is_enabled"),
    raw_id_fields=("payment_type_config",),
)
register_portal(
    RequestApprovalPurposeExceptionPurpose,
    "Назначение в исключении",
    "Назначения в исключениях",
    list_display=("id", "exception_config", "payment_purpose"),
    raw_id_fields=("exception_config", "payment_type_config", "payment_purpose"),
)
register_portal(
    RequestApprovalPurposeExceptionStepConfig,
    "Этап исключения",
    "Этапы исключений",
    list_display=("id", "exception_config", "step", "step_type", "is_enabled"),
    raw_id_fields=("exception_config", "telegram_chat"),
)
register_portal(
    RequestApprovalPurposeExceptionStepApproverConfig,
    "Согласующий исключения",
    "Согласующие исключений",
    list_display=("id", "step_config", "approver_user"),
    raw_id_fields=("step_config", "approver_user"),
)
register_portal(AutoRequestTemplate, "Автозаявка", "Автозаявки", AutoRequestTemplateAdmin)
register_portal(UserApprovalVacation, "Отпуск согласующего", "Отпуска согласующих", UserApprovalVacationAdmin)
