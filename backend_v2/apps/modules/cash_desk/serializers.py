from rest_framework import serializers

from apps.modules.telegram_approvals.models import TenantTelegramChat


class CashDeskConfigWriteSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    telegram_chat_id = serializers.IntegerField(allow_null=True, required=False)

    def validate(self, attrs):
        tenant = self.context["tenant"]
        chat_id = attrs.get("telegram_chat_id")
        if chat_id is not None and not TenantTelegramChat.objects.filter(tenant=tenant, pk=chat_id).exists():
            raise serializers.ValidationError({"telegram_chat_id": "Telegram-группа не найдена."})
        return attrs


class TransferTargetWriteSerializer(serializers.Serializer):
    to_wallet_id = serializers.IntegerField()
    to_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
