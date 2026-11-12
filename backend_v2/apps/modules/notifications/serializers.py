from rest_framework import serializers

from apps.modules.notifications.push_services import endpoint_allowed


class ActionItemSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.IntegerField()
    approval_id = serializers.IntegerField()
    step = serializers.IntegerField()
    step_type = serializers.CharField()
    title = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(allow_blank=True)
    type_code = serializers.CharField(allow_blank=True)
    type_label = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    link = serializers.CharField()


class ActionItemTenantSerializer(serializers.Serializer):
    subdomain = serializers.CharField()
    name = serializers.CharField()


class TenantActionItemSerializer(ActionItemSerializer):
    tenant = ActionItemTenantSerializer()


class PushSubscriptionKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=255)
    auth = serializers.CharField(max_length=255)


class PushSubscribeSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=2048)
    keys = PushSubscriptionKeysSerializer()

    def validate_endpoint(self, value):
        if not value.lower().startswith("https://"):
            raise serializers.ValidationError("Endpoint должен использовать https.", code="endpoint_not_https")
        if not endpoint_allowed(value):
            raise serializers.ValidationError(
                "Endpoint не относится к поддерживаемым push-сервисам.", code="endpoint_not_allowed"
            )
        return value


class PushUnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.CharField(max_length=2048)
