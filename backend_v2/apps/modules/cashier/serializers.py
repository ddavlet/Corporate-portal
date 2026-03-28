from collections.abc import Mapping
from rest_framework import serializers

from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.vendors.models import Vendor


class CashExpenseSerializer(serializers.ModelSerializer):
    external_id = serializers.CharField(max_length=20)
    has_request = serializers.BooleanField(read_only=True)
    has_paid_request = serializers.BooleanField(read_only=True)
    matched_request_id = serializers.IntegerField(read_only=True, allow_null=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), allow_null=True, required=False)

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
            "has_request",
            "has_paid_request",
            "matched_request_id",
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

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            mutable = dict(data)
            if "external_id" not in mutable and "id" in mutable:
                mutable["external_id"] = mutable.get("id")
            data = mutable
        return super().to_internal_value(data)

    def validate(self, attrs):
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

        attrs["expense_year"] = expense_at.year
        attrs["expense_month"] = expense_at.month
        attrs["expense_day"] = expense_at.day
        return attrs


class CashRevenueSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = CashRevenue
        fields = [
            "id",
            "title",
            "amount",
            "currency",
            "revenue_date",
            "category",
            "received_from",
            "payment_method",
            "reference_no",
            "status",
            "tags",
            "note",
            "payload",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["created_at", "created_by"]

