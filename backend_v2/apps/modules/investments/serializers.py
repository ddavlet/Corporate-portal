from rest_framework import serializers

from apps.modules.investments.models import InvestPayoutSchedule, InvestReturn, ProjectInvestment
from apps.modules.serializers_guard import reject_client_pk_on_create


def _normalize_currency(attrs: dict, key: str = "currency") -> None:
    val = attrs.get(key)
    if val is not None:
        attrs[key] = str(val).strip().upper()


class InvestReturnSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestReturn
        fields = [
            "id",
            "tenant",
            "date",
            "sum",
            "sum_uzs",
            "comment",
            "confirmed",
            "currency",
            "type",
            "recipient",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        return attrs


class InvestPayoutScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestPayoutSchedule
        fields = [
            "id",
            "tenant",
            "payout_date",
            "amount",
            "currency",
            "is_paid",
            "payment_amount",
            "comment",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        return attrs


class ProjectInvestmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectInvestment
        fields = [
            "id",
            "tenant",
            "date",
            "amount",
            "currency",
            "comment",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        return attrs
