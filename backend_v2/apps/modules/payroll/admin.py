from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.payroll.models import (
    BankPayrollEmployee,
    BankPayrollEmployeeAccount,
    Employee,
    PayrollBankEmployeeLink,
    PayrollCardBatch,
    PayrollCardPayout,
    PayrollCardSettings,
    PayrollDocument,
    PayrollExpectedCard,
    PayrollLine,
    PayrollPayout,
)


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


class _CardReadOnlyAdmin(admin.ModelAdmin):
    """Card payout data is written only by sync_payroll_card_payouts and the portal: view only, never deleted."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class BankPayrollEmployeeAdmin(_CardReadOnlyAdmin):
    list_display = ("id", "bank_client_id", "external_id", "full_name", "masked_card", "last_seen_at")
    search_fields = ("external_id", "full_name")


class BankPayrollEmployeeAccountAdmin(_CardReadOnlyAdmin):
    list_display = ("id", "bank_employee", "account_no", "source", "last_seen_at")
    list_select_related = ("bank_employee",)
    search_fields = ("account_no", "bank_employee__external_id")


class PayrollCardBatchAdmin(_CardReadOnlyAdmin):
    list_display = ("id", "transit_account", "num", "doc_date", "amount", "period_month", "tenant", "bank_expense")
    list_select_related = ("tenant",)
    list_filter = (("tenant", admin.EmptyFieldListFilter), "tenant")
    search_fields = ("num", "transit_account")


class PayrollCardPayoutAdmin(_CardReadOnlyAdmin):
    list_display = (
        "id", "paid_on", "amount", "period_month", "tenant", "batch", "bank_employee", "employee", "document",
    )
    list_select_related = ("tenant", "batch", "bank_employee", "employee", "document")
    list_filter = (("tenant", admin.EmptyFieldListFilter), ("batch", admin.EmptyFieldListFilter), "tenant")
    search_fields = ("bank_doc_key", "name_from_purpose")


class PayrollBankEmployeeLinkAdmin(_CardReadOnlyAdmin):
    list_display = ("id", "tenant", "bank_employee", "employee", "decided_by", "decided_at")
    list_select_related = ("tenant", "bank_employee", "employee", "decided_by")
    list_filter = ("tenant",)


class PayrollExpectedCardAdmin(_CardReadOnlyAdmin):
    list_display = ("id", "document", "employee", "amount", "is_manual", "updated_at")
    list_select_related = ("document", "employee")


class PayrollCardSettingsAdmin(admin.ModelAdmin):
    """The only editable card model: start period and the auto-close switch, per tenant."""

    list_display = ("id", "tenant", "card_start_period", "auto_close_enabled")
    list_select_related = ("tenant",)
    raw_id_fields = ("tenant",)

    def has_delete_permission(self, request, obj=None):
        return False


register_portal(PayrollDocument, "Начисление ЗП", "Начисления ЗП", PayrollDocumentAdmin)
register_portal(Employee, "Сотрудник", "Сотрудники", EmployeeAdmin)
register_portal(PayrollLine, "Строка начисления ЗП", "Строки начисления ЗП", PayrollLineAdmin)
register_portal(PayrollPayout, "Выплата ЗП", "Выплаты ЗП", PayrollPayoutAdmin)
register_portal(BankPayrollEmployee, "Сотрудник банка (ЗП-проект)", "Сотрудники банка (ЗП-проект)", BankPayrollEmployeeAdmin)
register_portal(
    BankPayrollEmployeeAccount, "Карточный счёт сотрудника банка", "Карточные счета сотрудников банка",
    BankPayrollEmployeeAccountAdmin,
)
register_portal(PayrollCardBatch, "Ведомость на карты", "Ведомости на карты", PayrollCardBatchAdmin)
register_portal(PayrollCardPayout, "Выплата ЗП на карту", "Выплаты ЗП на карту", PayrollCardPayoutAdmin)
register_portal(
    PayrollBankEmployeeLink, "Привязка сотрудника банка", "Привязки сотрудников банка", PayrollBankEmployeeLinkAdmin
)
register_portal(PayrollExpectedCard, "Ожидаемая карта", "Ожидаемая карта", PayrollExpectedCardAdmin)
register_portal(PayrollCardSettings, "Настройки выплат на карту", "Настройки выплат на карту", PayrollCardSettingsAdmin)
