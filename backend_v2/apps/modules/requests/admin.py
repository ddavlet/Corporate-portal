from django.contrib import admin
from django import forms

from apps.modules.requests.models import Approval, Request, Vendor
from apps.tenants.models import TenantUserRole


class RequestAdminForm(forms.ModelForm):
    class Meta:
        model = Request
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.tenant_id:
            requester_ids = TenantUserRole.objects.filter(
                tenant=self.instance.tenant,
                role=TenantUserRole.ROLE_REQUESTER,
            ).values_list("user_id", flat=True)
            self.fields["requester"].queryset = self.fields["requester"].queryset.filter(id__in=requester_ids)


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    form = RequestAdminForm
    list_display = (
        "id",
        "tenant",
        "created_at",
        "created_by",
        "submitted_at",
        "status",
        "vendor",
        "amount",
        "currency",
        "requester",
        "expense_id",
    )
    list_filter = ("tenant", "status", "currency")
    search_fields = ("title", "vendor", "requester__username", "payment_purpose", "expense_id")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "account_number", "created_at", "created_by")
    list_filter = ("tenant",)
    search_fields = ("name", "account_number")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "request",
        "step",
        "step_type",
        "approver_user",
        "decision",
        "message_sent",
        "decided_at",
    )
    list_filter = ("decision", "step_type", "message_sent")
    search_fields = ("request__id", "approver_user__username", "comment")

