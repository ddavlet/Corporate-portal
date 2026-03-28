from rest_framework import serializers

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.vendors.models import Vendor


class BankExpenseSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    has_request = serializers.BooleanField(read_only=True)
    has_paid_request = serializers.BooleanField(read_only=True)
    matched_request_id = serializers.IntegerField(read_only=True, allow_null=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), allow_null=True, required=False)

    class Meta:
        model = BankExpense
        fields = [
            "id",
            "created_at",
            "created_by",
            "row_no",
            "doc_date",
            "process_date",
            "doc_no",
            "account_name",
            "inn",
            "account_no",
            "mfo",
            "debit_turnover",
            "payment_purpose",
            "vendor",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]
        read_only_fields = ["created_at", "created_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if tenant and "vendor" in self.fields:
            self.fields["vendor"].queryset = Vendor.objects.filter(tenant=tenant, kind=Vendor.KIND_TRANSFER)

    def validate(self, attrs):
        vendor = attrs.get("vendor")
        if vendor is None and self.instance is not None:
            vendor = self.instance.vendor
        if vendor:
            if vendor.kind != Vendor.KIND_TRANSFER:
                raise serializers.ValidationError({"vendor": "Only vendors with type «перечисление» are allowed."})
            tenant = getattr(self.context.get("request"), "tenant", None)
            if tenant and vendor.tenant_id != tenant.id:
                raise serializers.ValidationError({"vendor": "Vendor must belong to this tenant."})
            if "vendor" in attrs and attrs["vendor"] is not None:
                attrs.setdefault("account_name", vendor.name)
                if vendor.inn:
                    attrs.setdefault("inn", vendor.inn)
                if vendor.account_number:
                    attrs.setdefault("account_no", vendor.account_number)
        return attrs


class BankRevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankRevenue
        fields = [
            "id",
            "created_at",
            "created_by",
            "row_no",
            "doc_date",
            "process_date",
            "doc_no",
            "account_name",
            "inn",
            "account_no",
            "mfo",
            "kredit_turnover",
            "payment_purpose",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

