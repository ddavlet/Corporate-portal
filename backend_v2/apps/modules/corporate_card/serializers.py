from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import serializers

from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.modules.bank_expenses.models import BankExpense
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.serializer_integration import assign_wallet_for_corporate_movement
from apps.tenants.permissions import has_effective_module_access
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


def _tashkent_date_from_datetime(dt: datetime):
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, TASHKENT_TZ)
    return timezone.localtime(dt, TASHKENT_TZ).date()


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
    bank_expense_exists = serializers.SerializerMethodField(read_only=True)
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
            "revenue_date",
            "confirmed",
            "direction",
            "organization",
            "unit",
            "employee",
            "cash_type",
            "operation",
            "account",
            "counterparty",
            "total_sum",
            "comment",
            "source_year",
            "title",
            "amount",
            "currency",
            "revenue_at",
            "note",
            "payload",
            "bank_expense_id",
            "wallet_id",
            "bank_expense_exists",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "created_by", "bank_expense_exists"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        attrs = super().validate(attrs)
        revenue_date = attrs.get("revenue_date")
        revenue_at = attrs.get("revenue_at")

        if revenue_date is None and self.instance is not None:
            revenue_date = self.instance.revenue_date
        if revenue_at is None and self.instance is not None:
            revenue_at = self.instance.revenue_at

        if revenue_date is None and revenue_at is not None:
            revenue_date = _tashkent_date_from_datetime(revenue_at)
            attrs["revenue_date"] = revenue_date

        if revenue_date is not None:
            attrs["source_year"] = revenue_date.year

        # Keep compatibility with existing generic fields.
        if "total_sum" in attrs and "amount" not in attrs:
            attrs["amount"] = attrs["total_sum"]

        if "comment" in attrs and "note" not in attrs:
            attrs["note"] = attrs["comment"]

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

    def validate_bank_expense_id(self, value):
        if value in (None, ""):
            return None

        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else None
        user = getattr(request, "user", None) if request else None
        if not tenant or not user:
            return value

        # Soft validation: enforce existence only when bank module is effectively enabled.
        if has_effective_module_access(user=user, tenant=tenant, module_key="bank"):
            exists = BankExpense.objects.filter(tenant=tenant, id=value).exists()
            if not exists:
                raise serializers.ValidationError("Bank expense not found for this tenant.")
        return value

    def get_bank_expense_exists(self, obj):
        if not obj.bank_expense_id:
            return False
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else getattr(obj, "tenant", None)
        if not tenant:
            return False
        return BankExpense.objects.filter(tenant=tenant, id=obj.bank_expense_id).exists()

