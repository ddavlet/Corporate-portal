from django.contrib import admin

from apps.modules.requests.models import Request


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "submitted_at", "status", "vendor", "amount", "currency", "expense_id")
    list_filter = ("tenant", "status", "currency")
    search_fields = ("title", "vendor", "requester", "payment_purpose", "expense_id")

