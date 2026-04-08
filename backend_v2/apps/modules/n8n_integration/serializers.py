from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.cashier.serializers import CashExpenseSerializer, CashRevenueSerializer
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import CardExpenseSerializer, CardRevenueSerializer
from apps.modules.notes.models import Note
from apps.modules.requests.expense_refs import (
    expense_ref_target_for,
    try_resolve_request_expense_ref_id,
)
from apps.modules.requests.models import Approval, Request
from apps.modules.vendors.models import Vendor
from apps.modules.vendors.serializers import VendorSerializer
from apps.tenants.permissions import has_effective_module_access
from apps.tenants.models import TenantMembership, TenantUserRole

User = get_user_model()


class N8nVendorImportSerializer(VendorSerializer):
    id = serializers.IntegerField(required=False)

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if isinstance(data, Mapping):
            data = dict(data)
            if "account_number" not in data and "account_no" in data:
                data["account_number"] = data.get("account_no")
        return serializers.ModelSerializer.to_internal_value(self, data)

    class Meta(VendorSerializer.Meta):
        read_only_fields = ["tenant", "created_at", "created_by"]


class N8nCashExpenseImportSerializer(CashExpenseSerializer):
    id = serializers.IntegerField(required=False)

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if isinstance(data, Mapping):
            data = dict(data)
        return serializers.ModelSerializer.to_internal_value(self, data)

    class Meta(CashExpenseSerializer.Meta):
        read_only_fields = [
            "expense_year",
            "expense_month",
            "expense_day",
            "created_at",
            "created_by",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]


class N8nCashRevenueImportSerializer(CashRevenueSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(CashRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nPayrollLineImportSerializer(serializers.ModelSerializer):
    """Upsert payroll line by id; doc_id ties to PayrollDocument (auto-created)."""

    id = serializers.IntegerField(required=False)
    doc_id = serializers.CharField(write_only=True)

    class Meta:
        model = PayrollLine
        fields = [
            "id",
            "doc_id",
            "line_no",
            "employee",
            "item",
            "description",
            "sum",
            "days_plan",
            "days_fact",
            "period_start",
            "period_end",
            "approval",
        ]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["doc_id"] = instance.document.doc_id
        return ret

    def create(self, validated_data):
        line_id = validated_data.pop("id")
        doc_id = validated_data.pop("doc_id")
        tenant = self.context["request"].tenant
        doc, _ = PayrollDocument.objects.get_or_create(tenant=tenant, doc_id=doc_id)
        return PayrollLine.objects.create(id=line_id, document=doc, **validated_data)

    def update(self, instance, validated_data):
        doc_id = validated_data.pop("doc_id", None)
        if doc_id is not None:
            tenant = self.context["request"].tenant
            doc, _ = PayrollDocument.objects.get_or_create(tenant=tenant, doc_id=doc_id)
            validated_data["document"] = doc
        validated_data.pop("id", None)
        return super().update(instance, validated_data)


class N8nBankExpenseImportSerializer(BankExpenseSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(BankExpenseSerializer.Meta):
        read_only_fields = [
            "created_at",
            "created_by",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]


class N8nBankRevenueImportSerializer(BankRevenueSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(BankRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardExpenseImportSerializer(CardExpenseSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(CardExpenseSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardRevenueImportSerializer(CardRevenueSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(CardRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by", "bank_expense_exists"]


class N8nRequestImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    requester = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    vendor_ref = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), required=False, allow_null=True)
    billing_date = serializers.DateField(required=False)
    description = serializers.CharField(allow_blank=True, required=False, default="")

    class Meta:
        model = Request
        fields = [
            "id",
            "company_payer",
            "category",
            "vendor",
            "vendor_ref",
            "title",
            "description",
            "amount",
            "currency",
            "payment_type",
            "urgency",
            "requester",
            "payment_purpose",
            "submitted_at",
            "status",
            "payed_at",
            "expense_id",
            "file_link",
            "expense_year",
            "expense_month",
            "expense_day",
            "billing_date",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            self.fields["vendor_ref"].queryset = Vendor.objects.filter(tenant=tenant)

    def validate_requester(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if value is None or tenant is None:
            return value
        is_member = TenantMembership.objects.filter(tenant=tenant, user=value, is_active=True).exists()
        roles = list(
            TenantUserRole.objects.filter(tenant=tenant, user=value).values_list("role", flat=True).distinct()
        )
        if not is_member:
            raise serializers.ValidationError(
                (
                    f"Requester must be an active tenant member. "
                    f"tenant_id={tenant.id}, tenant_subdomain={tenant.subdomain}, "
                    f"requester_id={value.id}, requester_username={value.username}, roles={roles}"
                )
            )
        if not TenantUserRole.objects.filter(
            tenant=tenant, user=value, role=TenantUserRole.ROLE_REQUESTER
        ).exists():
            raise serializers.ValidationError(
                (
                    f"Requester must have role 'requester' in this tenant. "
                    f"tenant_id={tenant.id}, tenant_subdomain={tenant.subdomain}, "
                    f"requester_id={value.id}, requester_username={value.username}, roles={roles}"
                )
            )
        return value

    def validate_vendor_ref(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if value is None or tenant is None:
            return value
        if value.tenant_id != tenant.id:
            raise serializers.ValidationError("Vendor must belong to this tenant.")
        return value

    def validate(self, attrs):
        tenant = getattr(self.context.get("request"), "tenant", None)
        vendor_ref = attrs.get("vendor_ref")
        payment_type = attrs.get("payment_type")
        if self.instance is not None:
            if vendor_ref is None and "vendor_ref" not in attrs:
                vendor_ref = self.instance.vendor_ref
            if payment_type is None:
                payment_type = self.instance.payment_type
        if vendor_ref and payment_type:
            expected_kind = Vendor.KIND_CASH if payment_type == Request.PAYMENT_TYPE_CASH else Vendor.KIND_TRANSFER
            if vendor_ref.kind != expected_kind:
                raise serializers.ValidationError(
                    {"vendor_ref": "Vendor payment type does not match request payment type."}
                )
            attrs["vendor"] = vendor_ref.name
        if self.instance is None and "billing_date" not in attrs:
            raise serializers.ValidationError({"billing_date": "This field is required."})
        if self.instance is None and "requester" not in attrs:
            raise serializers.ValidationError({"requester": "This field is required."})
        effective_payment_type = attrs.get("payment_type")
        if effective_payment_type is None and self.instance is not None:
            effective_payment_type = self.instance.payment_type
        effective_category = attrs.get("category")
        if effective_category is None and self.instance is not None:
            effective_category = self.instance.category
        expense_id_val = attrs.get("expense_id")
        if expense_id_val is None and self.instance is not None and "expense_id" not in attrs:
            expense_id_val = self.instance.expense_id
        effective_expense_year = attrs.get("expense_year")
        if effective_expense_year is None and self.instance is not None:
            effective_expense_year = self.instance.expense_year
        eid = str(expense_id_val or "").strip()
        if not eid:
            attrs["expense_ref_id"] = None
            attrs["expense_ref_target"] = None
        else:
            ref = try_resolve_request_expense_ref_id(
                tenant=tenant,
                payment_type=effective_payment_type,
                category=effective_category,
                expense_id_raw=expense_id_val,
                expense_year=effective_expense_year,
            )
            tgt = expense_ref_target_for(payment_type=effective_payment_type, category=effective_category) if ref else None
            attrs["expense_ref_id"] = ref
            attrs["expense_ref_target"] = tgt
        return attrs


class N8nApprovalImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    approver_user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    request = serializers.PrimaryKeyRelatedField(queryset=Request.objects.all())

    class Meta:
        model = Approval
        fields = [
            "id",
            "request",
            "approver_user",
            "approver_tg_id",
            "approver_tg_from_id",
            "message_id",
            "message_sent",
            "message_sent_at",
            "step",
            "step_type",
            "decision",
            "comment",
            "decided_at",
            "resend_batch_id",
            "resend_key",
            "replaced_approval",
        ]
        extra_kwargs = {
            "step": {"required": False},
            "step_type": {"required": False},
            "decision": {"required": False},
            "message_sent": {"required": False},
        }

    def validate_request(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant and value.tenant_id != tenant.id:
            raise serializers.ValidationError("Request must belong to this tenant.")
        return value

    def validate_approver_user(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if value is None or tenant is None:
            return value
        is_member = TenantMembership.objects.filter(tenant=tenant, user=value, is_active=True).exists()
        roles = list(
            TenantUserRole.objects.filter(tenant=tenant, user=value).values_list("role", flat=True).distinct()
        )
        if not is_member:
            raise serializers.ValidationError(
                (
                    f"Approver user must be an active tenant member. "
                    f"tenant_id={tenant.id}, tenant_subdomain={tenant.subdomain}, "
                    f"approver_user_id={value.id}, approver_username={value.username}, roles={roles}"
                )
            )
        return value

    def validate(self, attrs):
        if self.instance is None and "approver_user" not in attrs:
            raise serializers.ValidationError({"approver_user": "This field is required."})
        return attrs


TARGET_TO_MODULE = {
    Note.TARGET_REQUEST: "requests",
    Note.TARGET_CASH: "cash",
    Note.TARGET_BANK: "bank",
}


class N8nNoteImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Note
        fields = [
            "id",
            "recipient_user",
            "target_type",
            "target_id",
            "message",
            "delivery_status",
            "delivery_error",
            "sent_at",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["created_at", "created_by"]

    def validate_recipient_user(self, value):
        request = self.context["request"]
        tenant = request.tenant
        is_member = value.tenantmembership_set.filter(tenant=tenant, is_active=True).exists()
        if not is_member:
            raise serializers.ValidationError("Recipient must be an active tenant member.")
        if not value.telegram_chat_id:
            raise serializers.ValidationError("Recipient has no telegram_chat_id.")
        return value

    def validate(self, attrs):
        request = self.context["request"]
        tenant = request.tenant
        user = request.user
        target_type = attrs.get("target_type")
        target_id = attrs.get("target_id")
        if self.instance is not None:
            target_type = target_type if target_type is not None else self.instance.target_type
            target_id = target_id if target_id is not None else self.instance.target_id
        module_key = TARGET_TO_MODULE.get(target_type)
        if not module_key:
            raise serializers.ValidationError({"target_type": "Unsupported target type."})
        if not has_effective_module_access(user=user, tenant=tenant, module_key=module_key):
            raise serializers.ValidationError({"target_type": "No access to target module."})
        if target_type == Note.TARGET_REQUEST:
            exists = Request.objects.filter(tenant=tenant, id=target_id).exists()
        elif target_type == Note.TARGET_CASH:
            exists = CashExpense.objects.filter(tenant=tenant, id=target_id).exists()
        else:
            exists = BankExpense.objects.filter(tenant=tenant, id=target_id).exists()
        if not exists:
            raise serializers.ValidationError({"target_id": "Target entry not found in this tenant."})
        return attrs
