from rest_framework import serializers

from apps.modules.cash_desk.card_topup_config import available_users


class CardTopupNotifyConfigWriteSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    recipient_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)

    def validate(self, attrs):
        tenant = self.context["tenant"]
        ids = set(attrs.get("recipient_ids") or [])
        allowed = set(available_users(tenant).filter(id__in=ids).values_list("id", flat=True))
        if not ids.issubset(allowed):
            raise serializers.ValidationError({"recipient_ids": "Пользователь не состоит в компании."})
        if attrs["is_active"] and not ids:
            raise serializers.ValidationError({"recipient_ids": "Выберите хотя бы одного получателя."})
        attrs["recipient_ids"] = sorted(ids)
        return attrs
