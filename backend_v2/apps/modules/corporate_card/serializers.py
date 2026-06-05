from collections.abc import Mapping
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

CARD_REVENUE_LEGACY_PAYLOAD_KEYS = (
    "direction",
    "organization",
    "unit",
    "employee",
    "cash_type",
    "account",
)
CARD_REVENUE_LEGACY_PAYLOAD_EXTRA_KEYS = ("source_year",)


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
    revenue_date = serializers.SerializerMethodField(read_only=True)
    source_year = serializers.SerializerMethodField(read_only=True)
    direction = serializers.SerializerMethodField(read_only=True)
    organization = serializers.SerializerMethodField(read_only=True)
    unit = serializers.SerializerMethodField(read_only=True)
    employee = serializers.SerializerMethodField(read_only=True)
    cash_type = serializers.SerializerMethodField(read_only=True)
    account = serializers.SerializerMethodField(read_only=True)
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
            "currency",
            "revenue_at",
            "payload",
            "bank_expense_id",
            "wallet_id",
            "bank_expense_exists",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "bank_expense_exists",
            "revenue_date",
            "source_year",
            "direction",
            "organization",
            "unit",
            "employee",
            "cash_type",
            "account",
        ]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        attrs = super().validate(attrs)
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            attrs = assign_wallet_for_corporate_movement(instance=self.instance, tenant=tenant, attrs=attrs)
        return attrs

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            mutable = dict(data)
            if "revenue_at" not in mutable and "date" in mutable:
                mutable["revenue_at"] = mutable.get("date")
            if "total_sum" not in mutable and "amount" in mutable:
                mutable["total_sum"] = mutable.pop("amount")
            elif "amount" in mutable:
                mutable.pop("amount")
            if "comment" not in mutable and "note" in mutable:
                mutable["comment"] = mutable.pop("note")
            elif "note" in mutable:
                mutable.pop("note")
            title = mutable.pop("title", None)
            mutable.pop("revenue_date", None)
            if "revenue_at" in mutable:
                mutable["revenue_at"] = _normalize_datetime_input(mutable.get("revenue_at"))
            payload = mutable.get("payload")
            payload_dict = dict(payload) if isinstance(payload, Mapping) else {}
            if title not in (None, ""):
                if not str(mutable.get("operation") or "").strip():
                    mutable["operation"] = title
                else:
                    payload_dict["title"] = title
            for key in CARD_REVENUE_LEGACY_PAYLOAD_KEYS + CARD_REVENUE_LEGACY_PAYLOAD_EXTRA_KEYS:
                if key in mutable:
                    payload_dict[key] = mutable.pop(key)
            if payload_dict:
                mutable["payload"] = payload_dict
            data = mutable
        return super().to_internal_value(data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        payload = instance.payload or {}

        operation = str(data.get("operation") or "").strip()
        if not operation:
            operation = str(payload.get("title") or "")
        data["operation"] = operation

        comment = str(data.get("comment") or "").strip()
        if not comment:
            comment = str(payload.get("note") or "")
        data["comment"] = comment

        return data

    def _payload_value(self, obj, key: str) -> str:
        payload = obj.payload or {}
        value = payload.get(key)
        if value in (None, ""):
            return ""
        return str(value)

    def get_revenue_date(self, obj):
        if not obj.revenue_at:
            return None
        return _tashkent_date_from_datetime(obj.revenue_at).isoformat()

    def get_source_year(self, obj):
        payload = obj.payload or {}
        source_year = payload.get("source_year")
        if source_year not in (None, ""):
            try:
                return int(source_year)
            except (TypeError, ValueError):
                pass
        if obj.revenue_at:
            return _tashkent_date_from_datetime(obj.revenue_at).year
        return None

    def get_direction(self, obj):
        return self._payload_value(obj, "direction")

    def get_organization(self, obj):
        return self._payload_value(obj, "organization")

    def get_unit(self, obj):
        return self._payload_value(obj, "unit")

    def get_employee(self, obj):
        return self._payload_value(obj, "employee")

    def get_cash_type(self, obj):
        return self._payload_value(obj, "cash_type")

    def get_account(self, obj):
        return self._payload_value(obj, "account")

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

