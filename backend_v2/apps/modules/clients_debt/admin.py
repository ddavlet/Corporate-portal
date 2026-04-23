from django.contrib import admin

from apps.modules.clients_debt.models import ClientDebtSnapshot


@admin.register(ClientDebtSnapshot)
class ClientDebtSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "client", "debt_sum", "snapshot_at", "created_at")
    list_filter = ("tenant",)
    search_fields = ("client", "organization")
