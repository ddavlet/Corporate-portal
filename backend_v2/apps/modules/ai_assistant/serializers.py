from rest_framework import serializers


class AssistantMessageEventSerializer(serializers.Serializer):
    """`event: message` payload forwarded by tg-gateway."""

    event = serializers.CharField()
    payload = serializers.CharField(allow_blank=False, trim_whitespace=False)
    user_id = serializers.CharField()
    recipient_id = serializers.CharField()
    message_id = serializers.IntegerField()
    platform = serializers.CharField(required=False, default="telegram")
    bot_id = serializers.CharField(required=False, allow_blank=True, default="")
    chat_type = serializers.CharField(required=False, allow_blank=True, default="")
    sender_name = serializers.CharField(required=False, allow_blank=True, default="")
    mentions_bot = serializers.BooleanField(required=False, default=False)
    reply_to_message_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    reply_to_text = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")
    reply_to_from_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")
    reply_to_is_bot = serializers.BooleanField(required=False, default=False)
