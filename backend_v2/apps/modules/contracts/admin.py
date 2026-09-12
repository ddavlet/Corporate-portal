from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.contracts.models import Contract


class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "contract_number",
        "vendor",
        "date_from",
        "date_to",
        "contract_amount",
        "currency",
        "contract_status",
    )
    list_filter = ("tenant", "contract_status", "currency")
    search_fields = ("contract_number", "acc_number", "contract_terms")
    raw_id_fields = ("tenant", "vendor", "created_by")


register_portal(Contract, "Договор", "Договоры", ContractAdmin)
