from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import serializers

from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.serializer_integration import assign_wallet_for_corporate_movement
from apps.modules.requests.models import Request
from apps.modules.requests.request_required import is_request_required_for_expense

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


def _normalize_datetime_input(value):
    if value in (None, ""):
        return value
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return value
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return value
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, TASHKENT_TZ)
    return dt


class CardExpenseSerializer(serializers.ModelSerializer):
    has_request = serializers.BooleanField(read_only=True)
    has_paid_request = serializers.BooleanField(read_only=True)
    matched_request_id = serializers.IntegerField(read_only=True, allow_null=True)
    request_required = serializers.SerializerMethodField()
    wallet_id = serializers.PrimaryKeyRelatedField(
        source="wallet",
        queryset=Wallet.objects.none(),
        required=False,
        allow_null=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if tenant and "wallet_id" in self.fields:
            self.fields["wallet_id"].queryset = Wallet.objects.filter(
                tenant=tenant, wallet_type=Wallet.Type.CORPORATE_CARD
            )

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            attrs = assign_wallet_for_corporate_movement(instance=self.instance, tenant=tenant, attrs=attrs)
        return attrs

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if isinstance(data, Mapping):
            mutable = dict(data)
            if "expense_at" in mutable:
                mutable["expense_at"] = _normalize_datetime_input(mutable.get("expense_at"))
            data = mutable
        return super().to_internal_value(data)

    class Meta:
        model = CardExpense
        fields = [
            "id",
            "title",
            "amount",
            "currency",
            "expense_at",
            "note",
            "payload",
            "wallet_id",
            "has_request",
            "has_paid_request",
            "matched_request_id",
            "request_required",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def get_request_required(self, obj) -> bool:
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if not tenant:
            return True
        return is_request_required_for_expense(
            tenant=tenant,
            payment_type=Request.PAYMENT_TYPE_CARD,
            expense_obj=obj,
        )


class CardRevenueSerializer(serializers.ModelSerializer):
    wallet_id = serializers.PrimaryKeyRelatedField(
        source="wallet",
        queryset=Wallet.objects.none(),
        required=False,
        allow_null=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if tenant and "wallet_id" in self.fields:
            self.fields["wallet_id"].queryset = Wallet.objects.filter(
                tenant=tenant, wallet_type=Wallet.Type.CORPORATE_CARD
            )

    class Meta:
        model = CardRevenue
        fields = [
            "id",
            "external_id",
            "confirmed",
            "title",
            "amount",
            "currency",
            "revenue_at",
            "note",
            "payload",
            "wallet_id",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            attrs = assign_wallet_for_corporate_movement(instance=self.instance, tenant=tenant, attrs=attrs)
        return attrs

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if isinstance(data, Mapping):
            mutable = dict(data)
            if "revenue_at" not in mutable and "date" in mutable:
                mutable["revenue_at"] = mutable.get("date")
            if "revenue_at" in mutable:
                mutable["revenue_at"] = _normalize_datetime_input(mutable.get("revenue_at"))
            data = mutable
        return super().to_internal_value(data)
