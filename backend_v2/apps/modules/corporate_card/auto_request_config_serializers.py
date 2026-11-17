from rest_framework import serializers

from apps.modules.corporate_card.auto_request_config import (
    active_card_payment_purposes,
    current_card_auto_request_values,
    tenant_vendors,
)


class CardExpenseAutoRequestConfigWriteSerializer(serializers.Serializer):
    """PATCH payload; validation runs against the merged (stored + patched) values."""

    is_enabled = serializers.BooleanField(required=False)
    payment_purpose = serializers.CharField(required=False, allow_blank=True, max_length=200)
    category = serializers.CharField(required=False, allow_blank=True, max_length=100)
    company_payer = serializers.CharField(required=False, allow_blank=True, max_length=100)
    vendor_ref_id = serializers.IntegerField(required=False, allow_null=True)
    match_text = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate(self, attrs):
        tenant = self.context["tenant"]
        wallet = self.context["wallet"]
        for field in ("payment_purpose", "category", "company_payer", "match_text"):
            if field in attrs:
                attrs[field] = attrs[field].strip()

        current = current_card_auto_request_values(tenant=tenant, wallet=wallet)
        merged = {**current, **attrs}
        purpose = merged["payment_purpose"]
        if merged["is_enabled"] and not purpose:
            raise serializers.ValidationError({"payment_purpose": "Укажите назначение платежа."})
        # A stored purpose that was deactivated later must not block switching the setting off.
        if purpose and (merged["is_enabled"] or purpose != current["payment_purpose"]):
            allowed = {row["name"] for row in active_card_payment_purposes(tenant)}
            if purpose not in allowed:
                raise serializers.ValidationError(
                    {"payment_purpose": "Назначение не найдено среди активных для «Платежная карта»."}
                )

        vendor_ref_id = attrs.get("vendor_ref_id")
        if vendor_ref_id is not None and not tenant_vendors(tenant).filter(id=vendor_ref_id).exists():
            raise serializers.ValidationError({"vendor_ref_id": "Контрагент не найден."})
        return attrs
