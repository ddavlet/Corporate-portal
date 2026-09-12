from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.investments.models import (
    CbuExchangeRate,
    InvestCompany,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentFormConfig,
    InvestmentProjectApprovalConfig,
    InvestmentProjectApprovalConfigStep,
    InvestmentProjectApprovalConfigStepApprover,
    InvestmentReturnApproval,
    InvestNotificationConfig,
    InvestPayoutNotificationLog,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)


class InvestReturnAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "company", "date", "sum", "currency", "type", "recipient", "confirmed")
    list_filter = ("tenant", "confirmed", "type", "recipient")
    search_fields = ("comment",)
    raw_id_fields = ("tenant", "company", "payout_schedule", "created_by")
    date_hierarchy = "date"


class InvestPayoutScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "company",
        "payout_date",
        "amount",
        "payment_amount",
        "is_paid",
        "return_type",
        "recipient",
    )
    list_filter = ("tenant", "is_paid", "return_type", "recipient")
    raw_id_fields = ("tenant", "company", "created_return", "created_by")
    date_hierarchy = "payout_date"


class ProjectInvestmentAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "company", "date", "amount", "currency", "confirmed")
    list_filter = ("tenant", "confirmed")
    search_fields = ("comment",)
    raw_id_fields = ("tenant", "company", "created_by")
    date_hierarchy = "date"


class InvestCompanyAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "is_active")
    list_filter = ("tenant", "is_active")
    search_fields = ("name",)
    raw_id_fields = ("tenant", "created_by")


class InvestPayoutScheduleShareLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "company", "paid_filter", "is_active", "created_at")
    list_filter = ("tenant", "is_active", "paid_filter")
    raw_id_fields = ("tenant", "company", "created_by")
    readonly_fields = ("token",)


class InvestmentFormConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "uses_companies", "updated_at")
    autocomplete_fields = ("tenant",)


class InvestmentApprovalConfigStepApproverInline(admin.TabularInline):
    model = InvestmentApprovalConfigStepApprover
    extra = 0
    raw_id_fields = ("approver_user",)


class InvestmentApprovalConfigStepInline(admin.TabularInline):
    model = InvestmentApprovalConfigStep
    extra = 0
    show_change_link = True
    fields = ("step", "step_type", "is_enabled")


class InvestmentApprovalConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "return_type", "recipient", "is_enabled")
    list_filter = ("tenant", "return_type", "recipient")
    autocomplete_fields = ("tenant",)
    inlines = [InvestmentApprovalConfigStepInline]


class InvestmentApprovalConfigStepAdmin(admin.ModelAdmin):
    list_display = ("id", "config", "step", "step_type", "is_enabled")
    list_filter = ("step_type", "is_enabled")
    raw_id_fields = ("config", "telegram_chat")
    inlines = [InvestmentApprovalConfigStepApproverInline]


class InvestmentReturnApprovalAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "invest_return", "step", "step_type", "approver_user", "decision")
    list_filter = ("decision", "step_type", "tenant")
    raw_id_fields = ("tenant", "invest_return", "approver_user", "telegram_message")


class InvestNotificationConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "responsible_user", "days_before", "is_active")
    list_filter = ("is_active",)
    autocomplete_fields = ("tenant",)
    raw_id_fields = ("responsible_user", "telegram_chat")


class InvestPayoutNotificationLogAdmin(admin.ModelAdmin):
    list_display = ("id", "schedule", "recipient_user", "sent_date", "sent_at")
    raw_id_fields = ("schedule", "recipient_user")
    date_hierarchy = "sent_date"


class InvestmentProjectApprovalConfigStepApproverInline(admin.TabularInline):
    model = InvestmentProjectApprovalConfigStepApprover
    extra = 0
    raw_id_fields = ("approver_user",)


class InvestmentProjectApprovalConfigStepInline(admin.TabularInline):
    model = InvestmentProjectApprovalConfigStep
    extra = 0
    show_change_link = True
    fields = ("step", "step_type", "is_enabled")


class InvestmentProjectApprovalConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "is_enabled", "updated_at")
    autocomplete_fields = ("tenant",)
    inlines = [InvestmentProjectApprovalConfigStepInline]


class InvestmentProjectApprovalConfigStepAdmin(admin.ModelAdmin):
    list_display = ("id", "config", "step", "step_type", "is_enabled")
    list_filter = ("step_type", "is_enabled")
    raw_id_fields = ("config", "telegram_chat")
    inlines = [InvestmentProjectApprovalConfigStepApproverInline]


class ProjectInvestmentApprovalAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "project_investment", "step", "step_type", "approver_user", "decision")
    list_filter = ("decision", "step_type", "tenant")
    raw_id_fields = ("tenant", "project_investment", "approver_user", "telegram_message")


class CbuExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["date", "usd_uzs_rate", "updated_at"]
    ordering = ["-date"]


register_portal(InvestReturn, "Выплата", "Выплаты", InvestReturnAdmin)
register_portal(InvestPayoutSchedule, "Расписание выплат", "Расписание выплат", InvestPayoutScheduleAdmin)
register_portal(ProjectInvestment, "Заявка на вложение", "Заявки на вложение", ProjectInvestmentAdmin)
register_portal(InvestCompany, "Компания (инвестиции)", "Компании", InvestCompanyAdmin)
register_portal(
    InvestPayoutScheduleShareLink,
    "Ссылка на график выплат",
    "Ссылки на график выплат",
    InvestPayoutScheduleShareLinkAdmin,
)
register_portal(InvestmentFormConfig, "Форма создания", "Форма создания", InvestmentFormConfigAdmin)
register_portal(
    InvestmentApprovalConfig,
    "Этапы согласования выплат",
    "Этапы согласования выплат",
    InvestmentApprovalConfigAdmin,
)
register_portal(
    InvestmentApprovalConfigStep,
    "Этап согласования выплаты",
    "Этапы согласования выплат",
    InvestmentApprovalConfigStepAdmin,
)
register_portal(
    InvestmentApprovalConfigStepApprover,
    "Согласующий выплаты",
    "Согласующие выплат",
    list_display=("id", "step", "approver_user"),
    raw_id_fields=("step", "approver_user"),
)
register_portal(
    InvestmentReturnApproval,
    "Согласование выплаты",
    "Согласования выплат",
    InvestmentReturnApprovalAdmin,
)
register_portal(
    InvestNotificationConfig,
    "Инвестиции — уведомления о выплатах",
    "Инвестиции — уведомления о выплатах",
    InvestNotificationConfigAdmin,
)
register_portal(
    InvestPayoutNotificationLog,
    "Лог уведомления о выплате",
    "Логи уведомлений о выплатах",
    InvestPayoutNotificationLogAdmin,
)
register_portal(
    InvestmentProjectApprovalConfig,
    "Согласование заявок на вложение",
    "Согласование заявок на вложение",
    InvestmentProjectApprovalConfigAdmin,
)
register_portal(
    InvestmentProjectApprovalConfigStep,
    "Этап заявки на вложение",
    "Этапы заявок на вложение",
    InvestmentProjectApprovalConfigStepAdmin,
)
register_portal(
    InvestmentProjectApprovalConfigStepApprover,
    "Согласующий заявки на вложение",
    "Согласующие заявок на вложение",
    list_display=("id", "step", "approver_user"),
    raw_id_fields=("step", "approver_user"),
)
register_portal(
    ProjectInvestmentApproval,
    "Согласование заявки на вложение",
    "Согласования заявок на вложение",
    ProjectInvestmentApprovalAdmin,
)
register_portal(CbuExchangeRate, "Курс ЦБ (USD/UZS)", "Курсы ЦБ (USD/UZS)", CbuExchangeRateAdmin)
