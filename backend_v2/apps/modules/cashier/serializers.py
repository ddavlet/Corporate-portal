from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import serializers

from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.serializer_integration import assign_wallet_for_cash_movement
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


class CashExpenseSerializer(serializers.ModelSerializer):
    external_id = serializers.CharField(max_length=20)
    has_request = serializers.BooleanField(read_only=True)
    has_paid_request = serializers.BooleanField(read_only=True)
    matched_request_id = serializers.IntegerField(read_only=True, allow_null=True)
    request_required = serializers.SerializerMethodField()
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), allow_null=True, required=False)
    wallet_id = serializers.PrimaryKeyRelatedField(
        source="wallet",
        queryset=Wallet.objects.none(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = CashExpense
        fields = [
            "id",
            "external_id",
            "confirmed",
            "title",
            "amount",
            "currency",
            "expense_at",
            "expense_year",
            "expense_month",
            "expense_day",
            "note",
            "payload",
            "vendor",
            "wallet_id",
            "has_request",
            "has_paid_request",
            "matched_request_id",
            "request_required",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "expense_year", "expense_month", "expense_day", "created_at", "created_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if tenant and "vendor" in self.fields:
            self.fields["vendor"].queryset = Vendor.objects.filter(tenant=tenant, kind=Vendor.KIND_CASH)
        if tenant and "wallet_id" in self.fields:
            self.fields["wallet_id"].queryset = Wallet.objects.filter(
                tenant=tenant, wallet_type=Wallet.Type.CASH
            )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            mutable = dict(data)
            if "external_id" not in mutable and "id" in mutable:
                mutable["external_id"] = mutable.get("id")
            if "expense_at" in mutable:
                mutable["expense_at"] = _normalize_datetime_input(mutable.get("expense_at"))
            data = mutable
        return super().to_internal_value(data)

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        attrs = super().validate(attrs)

        vendor = attrs.get("vendor")
        if vendor is None and self.instance is not None:
            vendor = self.instance.vendor
        if vendor:
            if vendor.kind != Vendor.KIND_CASH:
                raise serializers.ValidationError({"vendor": "Only vendors with type «наличные» are allowed."})
            tenant = getattr(self.context.get("request"), "tenant", None)
            if tenant and vendor.tenant_id != tenant.id:
                raise serializers.ValidationError({"vendor": "Vendor must belong to this tenant."})
            t = attrs.get("title")
            if t is None and self.instance is not None:
                t = self.instance.title
            if not (t or "").strip():
                attrs["title"] = vendor.name

        expense_at = attrs.get("expense_at")
        if expense_at is None and self.instance is not None:
            expense_at = self.instance.expense_at
        if expense_at is None:
            raise serializers.ValidationError({"expense_at": "This field is required."})

        expense_tashkent_date = _tashkent_date_from_datetime(expense_at)
        attrs["expense_year"] = expense_tashkent_date.year
        attrs["expense_month"] = expense_tashkent_date.month
        attrs["expense_day"] = expense_tashkent_date.day

        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            attrs = assign_wallet_for_cash_movement(instance=self.instance, tenant=tenant, attrs=attrs)
        return attrs

    def get_request_required(self, obj) -> bool:
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if not tenant:
            return True
        return is_request_required_for_expense(
            tenant=tenant,
            payment_type=Request.PAYMENT_TYPE_CASH,
            expense_obj=obj,
        )


class CashRevenueSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
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
                tenant=tenant, wallet_type=Wallet.Type.CASH
            )

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        attrs = super().validate(attrs)

        source_year = attrs.get("source_year")
        if source_year is None and self.instance is not None:
            source_year = self.instance.source_year
        if source_year is None:
            revenue_at = attrs.get("revenue_at")
            if revenue_at is None and self.instance is not None:
                revenue_at = self.instance.revenue_at
            if revenue_at is not None:
                source_year = _tashkent_date_from_datetime(revenue_at).year
                attrs["source_year"] = source_year

        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            attrs = assign_wallet_for_cash_movement(instance=self.instance, tenant=tenant, attrs=attrs)
        wallet = attrs.get("wallet") or (self.instance.wallet if self.instance is not None else None)
        if wallet is None:
            raise serializers.ValidationError({"wallet_id": "Cash wallet is required."})
        return attrs

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            mutable = dict(data)
            if "revenue_at" not in mutable and "date" in mutable:
                mutable["revenue_at"] = mutable.get("date")
            if "revenue_at" in mutable:
                mutable["revenue_at"] = _normalize_datetime_input(mutable.get("revenue_at"))
            if "source_year" in mutable and mutable.get("source_year") not in (None, ""):
                try:
                    mutable["source_year"] = int(mutable.get("source_year"))
                except (TypeError, ValueError):
                    pass
            # Keep compatibility with wider legacy payload shape: store unknown import fields in payload.
            legacy_keys = ("direction", "organization", "unit", "employee", "cash_type", "contract", "account")
            payload = mutable.get("payload")
            payload_dict = dict(payload) if isinstance(payload, Mapping) else {}
            for key in legacy_keys:
                if key in mutable:
                    payload_dict[key] = mutable.pop(key)
            if "source_year" in mutable:
                payload_dict["source_year"] = mutable["source_year"]
            if payload_dict:
                mutable["payload"] = payload_dict
            data = mutable
        return super().to_internal_value(data)

    class Meta:
        model = CashRevenue
        fields = [
            "id",
            "external_id",
            "source_year",
            "revenue_at",
            "currency",
            "confirmed",
            "operation",
            "counterparty",
            "total_sum",
            "comment",
            "payload",
            "wallet_id",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["created_at", "created_by"]

