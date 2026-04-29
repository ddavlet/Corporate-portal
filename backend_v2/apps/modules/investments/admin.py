from django.contrib import admin

from apps.modules.investments.models import (
    InvestCompany,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
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
        "currency",
        "confirmed",
        "created_at",
        "last_edit_at",
    )
    list_filter = ("tenant", "type", "recipient", "confirmed")
    search_fields = ("recipient",)
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
