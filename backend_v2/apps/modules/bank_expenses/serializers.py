from rest_framework import serializers

from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.bank_expenses.tashkent_dates import TashkentFlexibleDateField
from apps.modules.vendors.models import Vendor


def _apply_expense_calendar_from_doc_date(attrs: dict, instance) -> None:
    """Fill expense_year/month/day from doc_date (already Asia/Tashkent calendar date) when omitted."""
    doc_date = attrs.get("doc_date")
    if doc_date is None and instance is not None:
        doc_date = instance.doc_date
    if doc_date is None:
        return
    if attrs.get("expense_year") is None:
        attrs["expense_year"] = doc_date.year
    if attrs.get("expense_month") is None:
        attrs["expense_month"] = doc_date.month
    if attrs.get("expense_day") is None:
        attrs["expense_day"] = doc_date.day


class BankExpenseSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    doc_date = TashkentFlexibleDateField()
    process_date = TashkentFlexibleDateField()
    expense_year = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=9999)
    expense_month = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=12)
    expense_day = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=31)
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
            "expense_year",
            "expense_month",
            "expense_day",
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
        reject_client_pk_on_create(self)
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
        _apply_expense_calendar_from_doc_date(attrs, self.instance)
        return attrs


class BankRevenueSerializer(serializers.ModelSerializer):
    doc_date = TashkentFlexibleDateField()
    process_date = TashkentFlexibleDateField()

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        return attrs

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

