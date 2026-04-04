from rest_framework import serializers

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.cashier.serializers import CashExpenseSerializer, CashRevenueSerializer
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import CardExpenseSerializer, CardRevenueSerializer
from apps.modules.notes.models import Note
from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor
from apps.modules.vendors.serializers import VendorSerializer
from apps.tenants.permissions import has_effective_module_access


class N8nVendorImportSerializer(VendorSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(VendorSerializer.Meta):
        read_only_fields = ["tenant", "created_at", "created_by"]


class N8nCashExpenseImportSerializer(CashExpenseSerializer):
    id = serializers.IntegerField(required=True)

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
    id = serializers.IntegerField(required=True)

    class Meta(CashRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nPayrollLineImportSerializer(serializers.ModelSerializer):
    """Upsert payroll line by id; doc_id ties to PayrollDocument (auto-created)."""

    id = serializers.IntegerField(required=True)
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
    id = serializers.IntegerField(required=True)

    class Meta(BankExpenseSerializer.Meta):
        read_only_fields = [
            "created_at",
            "created_by",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]


class N8nBankRevenueImportSerializer(BankRevenueSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(BankRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardExpenseImportSerializer(CardExpenseSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(CardExpenseSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardRevenueImportSerializer(CardRevenueSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(CardRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by", "bank_expense_exists"]


TARGET_TO_MODULE = {
    Note.TARGET_REQUEST: "requests",
    Note.TARGET_CASH: "cash",
    Note.TARGET_BANK: "bank",
}


class N8nNoteImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=True)

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
