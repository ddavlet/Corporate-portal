from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.clients_debt.models import ClientDebtSnapshot


class ClientDebtSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "snapshot_at",
        "client",
        "organization",
        "debt_sum",
        "quantity",
    )
    list_filter = ("tenant", "doc_type")
    search_fields = ("client", "client_id", "organization")
    raw_id_fields = ("tenant", "created_by")
    date_hierarchy = "snapshot_at"


register_portal(ClientDebtSnapshot, "Долг клиента", "Долги клиентов", ClientDebtSnapshotAdmin)
