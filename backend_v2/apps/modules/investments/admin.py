from django.contrib import admin

from apps.modules.investments.models import InvestReturn


@admin.register(InvestReturn)
class InvestReturnAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "date", "type", "recipient", "sum", "currency", "confirmed", "created_at")
    list_filter = ("tenant", "type", "recipient", "confirmed")
    search_fields = ("recipient",)
