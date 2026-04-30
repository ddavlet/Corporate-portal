from rest_framework import serializers


class MessagingGatewayCallbackSerializer(serializers.Serializer):
    event = serializers.CharField()
    payload = serializers.CharField()
    user_id = serializers.CharField()
    recipient_id = serializers.CharField()
    message_id = serializers.IntegerField()
    platform = serializers.CharField(default="telegram")
