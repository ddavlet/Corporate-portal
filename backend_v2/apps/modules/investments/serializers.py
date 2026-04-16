from rest_framework import serializers

from apps.modules.investments.models import InvestReturn
from apps.modules.serializers_guard import reject_client_pk_on_create


class InvestReturnSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestReturn
        fields = [
            "id",
            "tenant",
            "date",
            "sum",
            "comment",
            "confirmed",
            "currency",
            "type",
            "recipient",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        currency = attrs.get("currency")
        if currency is not None:
            attrs["currency"] = str(currency).strip().upper()
        return attrs
