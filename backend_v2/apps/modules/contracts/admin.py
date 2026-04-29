from django.contrib import admin

from apps.modules.contracts.models import Contract


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "vendor", "contract_number", "date_from", "date_to", "contract_status", "currency")
    list_filter = ("contract_status", "currency")
    search_fields = ("contract_number", "vendor__name", "tenant__subdomain")
    raw_id_fields = ("tenant", "vendor", "created_by")
