from django.contrib.auth import get_user_model
import json
import re
from rest_framework import serializers

from apps.tenants.cash_expense_id_format import validate_cash_expense_external_id_prefix
from apps.tenants.models import TenantUserRole

User = get_user_model()
PREFERENCE_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
PREFERENCE_MAX_BYTES = 16_384


class TenantModuleConfigSerializer(serializers.Serializer):
    module_key = serializers.CharField(max_length=100)
    is_enabled = serializers.BooleanField()


class TenantModuleConfigUpdateSerializer(serializers.Serializer):
    items = TenantModuleConfigSerializer(many=True)


class ModuleCatalogRowSerializer(serializers.Serializer):
    module_key = serializers.CharField(max_length=100)
    display_name = serializers.CharField()
    tenant_enabled = serializers.BooleanField()
    user_allowed = serializers.BooleanField()
    effective_enabled = serializers.BooleanField()


class TenantCashExpenseIdFormatSerializer(serializers.Serializer):
    cash_expense_external_id_prefix = serializers.CharField(max_length=32, allow_blank=True)
    cash_expense_external_id_digit_width = serializers.IntegerField(min_value=1, max_value=32)

    def validate_cash_expense_external_id_prefix(self, value):
        try:
            return validate_cash_expense_external_id_prefix(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class TenantPayrollDocIdFormatSerializer(serializers.Serializer):
    payroll_doc_id_prefix = serializers.CharField(max_length=32, allow_blank=True)
    payroll_doc_id_digit_width = serializers.IntegerField(min_value=1, max_value=32)

    def validate_payroll_doc_id_prefix(self, value):
        try:
            return validate_cash_expense_external_id_prefix(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


_ALLOWED_TENANT_ROLE_VALUES = {choice[0] for choice in TenantUserRole.ROLE_CHOICES}


class AccessMatrixAssignmentSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    roles = serializers.ListField(child=serializers.CharField(max_length=30), allow_empty=False)

    def validate_roles(self, value: list[str]) -> list[str]:
        unknown = [r for r in value if r not in _ALLOWED_TENANT_ROLE_VALUES]
        if unknown:
            raise serializers.ValidationError(f"Unknown roles: {sorted(set(unknown))}")
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate roles are not allowed.")
        return value


class AccessMatrixUpdateSerializer(serializers.Serializer):
    assignments = serializers.ListField(child=AccessMatrixAssignmentSerializer(), allow_empty=False)


class TenantIntegrationConfigSerializer(serializers.Serializer):
    telegram_bot_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    telegram_bot_username = serializers.CharField(required=False, allow_blank=True, max_length=128)
    requests_file_gateway_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    telegram_oidc_client_id = serializers.CharField(required=False, allow_blank=True, max_length=120)
    telegram_oidc_client_secret = serializers.CharField(required=False, allow_blank=True, write_only=True)
    telegram_oidc_redirect_uri = serializers.CharField(required=False, allow_blank=True)
    messaging_gateway_feedback_recipient_id = serializers.IntegerField(required=False, allow_null=True)
    messaging_gateway_feedback_action = serializers.CharField(required=False, allow_blank=True, max_length=100)
    request_ai_chat_webhook_url = serializers.URLField(required=False, allow_blank=True, max_length=500)

    def validate_request_ai_chat_webhook_url(self, value: str) -> str:
        url = (value or "").strip()
        if not url:
            return ""
        if "/webhook/" not in url:
            raise serializers.ValidationError("URL must contain /webhook/ (n8n Chat Trigger).")
        return url


class TenantUserPreferenceSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=120)
    value = serializers.JSONField()

    def validate_key(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if not PREFERENCE_KEY_PATTERN.match(normalized):
            raise serializers.ValidationError("Key must contain only lowercase letters, digits, dots, underscores, dashes.")
        return normalized

    def validate_value(self, value):
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > PREFERENCE_MAX_BYTES:
            raise serializers.ValidationError("Value is too large.")
        return value


