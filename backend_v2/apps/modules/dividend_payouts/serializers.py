from rest_framework import serializers

from apps.modules.dividend_payouts.models import DividendPayoutRule
from apps.modules.dividend_payouts.services_config import allowed_return_types

PURPOSE_REQUIRED_MESSAGE = "Укажите назначение платежа."
PURPOSE_DUPLICATE_MESSAGE = "Правило для этого назначения платежа уже есть."
RETURN_TYPE_DISABLED_MESSAGE = "Этот тип выплат отключён в настройках формы инвестиций."


class DividendPayoutRuleSerializer(serializers.ModelSerializer):
    payment_purpose = serializers.CharField(
        max_length=200,
        error_messages={"blank": PURPOSE_REQUIRED_MESSAGE, "required": PURPOSE_REQUIRED_MESSAGE},
    )

    class Meta:
        model = DividendPayoutRule
        fields = ["id", "payment_purpose", "return_type", "recipient", "is_active"]
        read_only_fields = ["id"]
        # Case-insensitive uniqueness is checked in validate() with a Russian message.
        validators = []

    def validate_payment_purpose(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError(PURPOSE_REQUIRED_MESSAGE)
        return value

    def validate(self, attrs):
        tenant = self.context["tenant"]

        purpose = attrs.get("payment_purpose")
        if purpose is not None:
            duplicates = DividendPayoutRule.objects.filter(tenant=tenant, payment_purpose__iexact=purpose)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({"payment_purpose": PURPOSE_DUPLICATE_MESSAGE})

        return_type = attrs.get("return_type")
        if return_type is not None:
            allowed = allowed_return_types(tenant)
            if allowed and return_type not in allowed:
                raise serializers.ValidationError({"return_type": RETURN_TYPE_DISABLED_MESSAGE})
        return attrs
