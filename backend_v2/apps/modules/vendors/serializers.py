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
        account_number = attrs.get("account_number", serializers.empty)
        if account_number is serializers.empty and self.instance is not None:
            account_number = self.instance.account_number
        if account_number is serializers.empty:
            account_number = None
        account_number = (str(account_number).strip() if account_number else "") or None
        attrs["account_number"] = account_number

        if kind == Vendor.KIND_TRANSFER:
            if not inn:
                raise serializers.ValidationError({"inn": "ИНН обязателен для поставщиков с типом «перечисление»."})
            attrs["inn"] = inn
        elif kind == Vendor.KIND_CASH:
            attrs["inn"] = inn

        # Pre-validate unique constraint to return 400 instead of IntegrityError.
        if tenant and account_number:
            qs = Vendor.objects.filter(tenant=tenant, account_number=account_number)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"account_number": "Расчетный счет уже используется у другого поставщика."})
        return attrs
