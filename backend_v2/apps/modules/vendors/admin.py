from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.vendors.models import Vendor


class VendorAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "kind", "inn", "account_number")
    list_filter = ("tenant", "kind")
    search_fields = ("name", "inn", "account_number")
    autocomplete_fields = ("tenant",)
    raw_id_fields = ("created_by",)


register_portal(Vendor, "Поставщик", "Поставщики", VendorAdmin)
