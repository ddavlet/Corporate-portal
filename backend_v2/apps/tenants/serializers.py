from django.contrib.auth import get_user_model
import json
import re
from rest_framework import serializers

from apps.tenants.models import TenantModuleConfig, TenantMembership, Tenant

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


class TenantIntegrationConfigSerializer(serializers.Serializer):
    telegram_bot_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    telegram_bot_username = serializers.CharField(required=False, allow_blank=True, max_length=128)
    telegram_approvals_bridge_dispatch_url = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_send_action = serializers.CharField(required=False, allow_blank=True, max_length=100)
    telegram_approvals_edit_action = serializers.CharField(required=False, allow_blank=True, max_length=100)
    telegram_approvals_draft_notification_action = serializers.CharField(
        required=False, allow_blank=True, max_length=100
    )
    telegram_approvals_message_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_header_new_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_header_step_approved_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_header_fully_approved_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_header_closed_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_header_rejected_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_subheader_payment_responsible_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_subheader_rejected_by_template = serializers.CharField(required=False, allow_blank=True)
    telegram_approvals_bridge_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    n8n_integration_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    requests_file_gateway_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    portal_feedback_telegram_chat_id = serializers.IntegerField(required=False, allow_null=True)
    portal_feedback_telegram_action = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate(self, attrs):
        raw = attrs.get("telegram_approvals_bridge_dispatch_url")
        if raw and not (raw.startswith("http://") or raw.startswith("https://")):
            raise serializers.ValidationError({"telegram_approvals_bridge_dispatch_url": "Must be an absolute URL."})
        return attrs


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


