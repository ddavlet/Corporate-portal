from django.contrib import admin

from apps.modules.investments.models import InvestPayoutSchedule, InvestReturn, ProjectInvestment


@admin.register(InvestReturn)
class InvestReturnAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
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
    list_display = ("id", "tenant", "date", "amount", "currency", "created_at", "last_edit_at")
    list_filter = ("tenant",)
    readonly_fields = ("created_at", "last_edit_at")
