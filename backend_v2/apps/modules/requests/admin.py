from django.contrib import admin
from django import forms

from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepConfig,
    RequestApprovalStepApproverConfig,
    UserRequestApproval,
)
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
    search_fields = ("title", "vendor", "vendor_ref__name", "requester__username", "payment_purpose", "expense_id")

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


class RequestApprovalStepApproverConfigInline(admin.TabularInline):
    model = RequestApprovalStepApproverConfig
    extra = 0


class RequestApprovalStepConfigInline(admin.TabularInline):
    model = RequestApprovalStepConfig
    extra = 0
    inlines = [RequestApprovalStepApproverConfigInline]


class RequestApprovalPaymentTypeConfigInline(admin.TabularInline):
    model = RequestApprovalPaymentTypeConfig
    extra = 0
    inlines = [RequestApprovalStepConfigInline]


@admin.register(RequestApprovalConfig)
class RequestApprovalConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "updated_at", "updated_by")
    search_fields = ("tenant__subdomain",)
    inlines = [RequestApprovalPaymentTypeConfigInline]


@admin.register(UserRequestApproval)
class UserRequestApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "approver_user",
        "request",
        "step",
        "step_type",
        "decision",
        "decided_at",
    )
    list_filter = ("decision", "step_type", "step")
    search_fields = ("approver_user__username", "request__id")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # This proxy admin maps to the production approvals table.
        # Allow full field editing only for superusers.
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

