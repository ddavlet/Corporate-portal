from rest_framework import serializers

from apps.modules.vendors.models import Vendor


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = [
            "id",
            "tenant",
            "kind",
            "name",
            "inn",
            "account_number",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "created_by"]

    def validate(self, attrs):
        kind = attrs.get("kind")
        if kind is None and self.instance is not None:
            kind = self.instance.kind

        inn = attrs.get("inn", serializers.empty)
        if inn is serializers.empty and self.instance is not None:
            inn = self.instance.inn
        if inn is serializers.empty:
            inn = None
        inn = (str(inn).strip() if inn else "") or None

        if kind == Vendor.KIND_TRANSFER:
            if not inn:
                raise serializers.ValidationError({"inn": "ИНН обязателен для поставщиков с типом «перечисление»."})
            attrs["inn"] = inn
        elif kind == Vendor.KIND_CASH:
            attrs["inn"] = None
        return attrs
