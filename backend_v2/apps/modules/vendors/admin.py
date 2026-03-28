from django.contrib import admin

from apps.modules.vendors.models import Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "kind", "name", "inn", "account_number", "created_at", "created_by")
    list_filter = ("tenant", "kind")
    search_fields = ("name", "inn", "account_number")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
