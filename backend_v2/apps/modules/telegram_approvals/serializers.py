from rest_framework import serializers


class TelegramApprovalWebhookSerializer(serializers.Serializer):
    update = serializers.JSONField(required=False)
    callback_query = serializers.JSONField(required=False)
    message = serializers.JSONField(required=False)

    def validate(self, attrs):
        if attrs.get("update"):
            return attrs
        if attrs.get("callback_query") or attrs.get("message"):
            return attrs
        raise serializers.ValidationError({"detail": "Payload must contain update or callback_query/message fields."})

