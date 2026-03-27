from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.notes.models import Note
from apps.modules.requests.models import Request
from apps.tenants.permissions import has_effective_module_access

User = get_user_model()


TARGET_TO_MODULE = {
    Note.TARGET_REQUEST: "requests",
    Note.TARGET_CASH: "cash",
    Note.TARGET_BANK: "bank",
}


class RecipientOptionSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "username", "telegram_chat_id"]

    def get_full_name(self, obj):
        return (obj.full_name or "").strip() or obj.username


class NoteSerializer(serializers.ModelSerializer):
    created_by_full_name = serializers.SerializerMethodField()
    recipient_full_name = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            "id",
            "target_type",
            "target_id",
            "message",
            "delivery_status",
            "delivery_error",
            "sent_at",
            "created_at",
            "created_by",
            "created_by_full_name",
            "recipient_user",
            "recipient_full_name",
        ]
        read_only_fields = [
            "delivery_status",
            "delivery_error",
            "sent_at",
            "created_at",
            "created_by",
            "created_by_full_name",
            "recipient_full_name",
        ]

    def get_created_by_full_name(self, obj):
        full_name = (getattr(obj.created_by, "full_name", "") or "").strip()
        return full_name or getattr(obj.created_by, "username", "")

    def get_recipient_full_name(self, obj):
        full_name = (getattr(obj.recipient_user, "full_name", "") or "").strip()
        return full_name or getattr(obj.recipient_user, "username", "")


class NoteCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Note
        fields = ["recipient_user", "target_type", "target_id", "message"]

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
        target_type = attrs["target_type"]
        target_id = attrs["target_id"]
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
