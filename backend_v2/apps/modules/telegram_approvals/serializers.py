from rest_framework import serializers

from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.modules.telegram_approvals.models import TenantTelegramChat


class TenantTelegramChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantTelegramChat
        fields = ["id", "name", "chat_id", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        return attrs


class MessagingGatewayCallbackSerializer(serializers.Serializer):
    event = serializers.CharField()
    payload = serializers.CharField()
    user_id = serializers.CharField()
    recipient_id = serializers.CharField()
    message_id = serializers.IntegerField(required=False, allow_null=True)
    platform = serializers.CharField(default="telegram")
    # Numeric Telegram bot id (token prefix before ':'). Never the bot secret.
    bot_id = serializers.CharField(required=False, allow_blank=True, default="")
