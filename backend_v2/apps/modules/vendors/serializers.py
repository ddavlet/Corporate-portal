from rest_framework import serializers

from apps.modules.serializers_guard import reject_client_pk_on_create
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
        reject_client_pk_on_create(self)
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else None
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
            # Pre-validate unique constraint to return 400 instead of IntegrityError.
            if tenant and inn:
                qs = Vendor.objects.filter(tenant=tenant, kind=Vendor.KIND_TRANSFER, inn=inn)
                if self.instance is not None:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError({"inn": "ИНН уже используется у другого поставщика."})
        elif kind == Vendor.KIND_CASH:
            attrs["inn"] = None
        return attrs
