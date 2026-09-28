from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine, PayrollPayout


class PayrollLineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0
    raw_id_fields = ("employee_fk",)


class PayrollDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "doc_id", "created_at", "created_by")
    list_filter = ("tenant",)
    search_fields = ("id", "doc_id")
    raw_id_fields = ("tenant", "created_by")
    inlines = [PayrollLineInline]


class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "full_name", "created_at")
    list_filter = ("tenant",)
    search_fields = ("full_name",)
    raw_id_fields = ("tenant", "created_by")


class PayrollLineAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "line_no", "employee", "item", "sum")
    search_fields = ("employee", "item", "description")
    raw_id_fields = ("document", "employee_fk")


class PayrollPayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "employee", "cash_expense", "amount", "created_at")
    list_filter = ("tenant",)
    raw_id_fields = ("tenant", "document", "employee", "cash_expense", "created_by")
    readonly_fields = ("document", "employee", "cash_expense", "amount", "created_at")

    def has_delete_permission(self, request, obj=None):
        # Deleting a payout row without also deleting/adjusting its CashExpense would
        # let payout_state()'s per-employee "remaining" silently grow back — and it
        # frees up an external_id suffix that create_payout_expense's sequencing then
        # relies on staying taken. Payouts are immutable ledger rows; keep them.
        return False


register_portal(PayrollDocument, "Начисление ЗП", "Начисления ЗП", PayrollDocumentAdmin)
register_portal(Employee, "Сотрудник", "Сотрудники", EmployeeAdmin)
register_portal(PayrollLine, "Строка начисления ЗП", "Строки начисления ЗП", PayrollLineAdmin)
register_portal(PayrollPayout, "Выплата ЗП", "Выплаты ЗП", PayrollPayoutAdmin)
