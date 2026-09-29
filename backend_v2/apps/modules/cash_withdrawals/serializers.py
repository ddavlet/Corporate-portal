from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.modules.wallets.models import Wallet
from apps.tenants.models import TenantMembership

User = get_user_model()


class RuleSerializer(serializers.Serializer):
    payment_type = serializers.CharField(max_length=50)
    payment_purpose = serializers.CharField(max_length=200)
    wallet_id = serializers.IntegerField()


class CashWithdrawalConfigWriteSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    card_telegram_chat_id = serializers.IntegerField(allow_null=True, required=False)
    alert_telegram_chat_id = serializers.IntegerField(allow_null=True, required=False)
    alert_after_days = serializers.IntegerField(min_value=1, max_value=365)
    alert_repeat_every_days = serializers.IntegerField(min_value=1, max_value=365)
    alert_hour = serializers.IntegerField(min_value=0, max_value=23)
    confirmer_user_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)
    alert_recipient_user_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)
    rules = RuleSerializer(many=True)

    def validate(self, attrs):
        tenant = self.context["tenant"]
        member_ids = set(
            TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
        )
        for field in ("confirmer_user_ids", "alert_recipient_user_ids"):
            ids = set(attrs.get(field) or [])
            if not ids.issubset(member_ids):
                raise serializers.ValidationError({field: "Пользователь не состоит в компании."})
            attrs[field] = sorted(ids)
        for field in ("card_telegram_chat_id", "alert_telegram_chat_id"):
            chat_id = attrs.get(field)
            if chat_id is not None and not TenantTelegramChat.objects.filter(tenant=tenant, pk=chat_id).exists():
                raise serializers.ValidationError({field: "Telegram-группа не найдена."})
        seen = set()
        wallet_ids = {r["wallet_id"] for r in attrs["rules"]}
        valid_wallets = set(
            Wallet.objects.filter(tenant=tenant, wallet_type=Wallet.Type.CASH, pk__in=wallet_ids).values_list("pk", flat=True)
        )
        for rule in attrs["rules"]:
            rule["payment_type"] = rule["payment_type"].strip()
            rule["payment_purpose"] = rule["payment_purpose"].strip()
            key = (rule["payment_type"].casefold(), rule["payment_purpose"].casefold())
            if key in seen:
                raise serializers.ValidationError({"rules": "Правило для этого назначения уже есть."})
            seen.add(key)
            if rule["wallet_id"] not in valid_wallets:
                raise serializers.ValidationError({"rules": "Касса не найдена или не является кассой наличных."})
        if attrs["is_active"]:
            if not attrs["rules"]:
                raise serializers.ValidationError({"rules": "Добавьте хотя бы одно правило."})
            if not attrs["confirmer_user_ids"]:
                raise serializers.ValidationError({"confirmer_user_ids": "Выберите хотя бы одного подтверждающего."})
        return attrs
