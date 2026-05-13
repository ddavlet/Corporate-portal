from django.contrib import admin

from apps.modules.investments.models import (
    InvestCompany,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentReturnApproval,
    ProjectInvestment,
)


@admin.register(InvestReturn)
class InvestReturnAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "company",
        "date",
        "type",
        "recipient",
        "sum",
        "sum_uzs",
        "currency",
        "cbu_usd_uzs_rate",
        "confirmed",
        "created_at",
        "last_edit_at",
    )
    list_filter = ("tenant", "type", "recipient", "confirmed")
    search_fields = ("recipient", "comment", "id")
    readonly_fields = ("created_at", "last_edit_at")


@admin.register(InvestPayoutSchedule)
class InvestPayoutScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "company",
        "payout_date",
        "amount",
        "currency",
        "is_paid",
        "payment_amount",
        "created_at",
        "last_edit_at",
    )
    list_filter = ("tenant", "is_paid", "currency")
    readonly_fields = ("created_at", "last_edit_at")


@admin.register(ProjectInvestment)
class ProjectInvestmentAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "company", "date", "amount", "currency", "created_at", "last_edit_at")
    list_filter = ("tenant",)
    readonly_fields = ("created_at", "last_edit_at")


@admin.register(InvestCompany)
class InvestCompanyAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "is_active", "created_at", "last_edit_at")
    list_filter = ("tenant", "is_active")
    search_fields = ("name",)
    readonly_fields = ("created_at", "last_edit_at")


@admin.register(InvestPayoutScheduleShareLink)
class InvestPayoutScheduleShareLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "company", "paid_filter", "is_active", "created_at")
    list_filter = ("tenant", "paid_filter", "is_active")
    search_fields = ("token",)
    readonly_fields = ("token", "created_at")


class InvestmentApprovalConfigStepApproverInline(admin.TabularInline):
    model = InvestmentApprovalConfigStepApprover
    extra = 0
    autocomplete_fields = ("approver_user",)


class InvestmentApprovalConfigStepInline(admin.TabularInline):
    model = InvestmentApprovalConfigStep
    extra = 0
    fields = ("step", "step_type", "is_enabled", "payment_chat_id")
    show_change_link = True


@admin.register(InvestmentApprovalConfig)
class InvestmentApprovalConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "return_type", "is_enabled", "created_at", "updated_at")
    list_filter = ("is_enabled", "tenant")
    search_fields = ("tenant__subdomain", "tenant__name")
    autocomplete_fields = ("tenant",)
    inlines = [InvestmentApprovalConfigStepInline]


@admin.register(InvestmentApprovalConfigStep)
class InvestmentApprovalConfigStepAdmin(admin.ModelAdmin):
    list_display = ("id", "config", "step", "step_type", "is_enabled", "payment_chat_id")
    list_filter = ("step_type", "is_enabled", "config__tenant")
    search_fields = ("config__tenant__subdomain", "config__tenant__name")
    autocomplete_fields = ("config",)
    inlines = [InvestmentApprovalConfigStepApproverInline]


@admin.register(InvestmentReturnApproval)
class InvestmentReturnApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "invest_return",
        "step",
        "step_type",
        "approver_user",
        "decision",
        "message_sent",
        "gateway_message_id",
        "decided_at",
    )
    list_filter = ("decision", "step_type", "message_sent", "tenant")
    search_fields = ("approver_user__username", "invest_return__id", "decision_comment")
    autocomplete_fields = ("tenant", "invest_return", "approver_user")
    readonly_fields = ("created_at", "updated_at")
