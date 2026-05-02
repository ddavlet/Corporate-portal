from django.contrib.auth import get_user_model
import json
import re
from rest_framework import serializers

from apps.tenants.cash_expense_id_format import validate_cash_expense_external_id_prefix

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


class TenantIntegrationConfigSerializer(serializers.Serializer):
    telegram_bot_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    telegram_bot_username = serializers.CharField(required=False, allow_blank=True, max_length=128)
    requests_file_gateway_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    telegram_oidc_client_id = serializers.CharField(required=False, allow_blank=True, max_length=120)
    telegram_oidc_client_secret = serializers.CharField(required=False, allow_blank=True, write_only=True)
    telegram_oidc_redirect_uri = serializers.CharField(required=False, allow_blank=True)
    messaging_gateway_feedback_recipient_id = serializers.IntegerField(required=False, allow_null=True)
    messaging_gateway_feedback_action = serializers.CharField(required=False, allow_blank=True, max_length=100)


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


