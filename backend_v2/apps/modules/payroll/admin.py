from django.contrib import admin

from apps.modules.payroll.models import PayrollDocument, PayrollLine


class PayrollLineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0


@admin.register(PayrollDocument)
class PayrollDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "doc_id", "created_at")
    list_filter = ("tenant",)
    search_fields = ("doc_id",)
    inlines = [PayrollLineInline]


@admin.register(PayrollLine)
class PayrollLineAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "line_no", "employee", "item", "sum")
    list_filter = ("document__tenant",)
    search_fields = ("employee", "item", "document__doc_id")
