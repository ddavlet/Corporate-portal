from rest_framework import serializers

from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.bank_expenses.tashkent_dates import TashkentFlexibleDateField
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.serializer_integration import assign_wallet_for_bank_movement
from apps.modules.requests.models import Request
from apps.modules.requests.request_required import is_request_required_for_expense


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
    request_required = serializers.SerializerMethodField()
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), allow_null=True, required=False)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    account_no = serializers.CharField(write_only=True, required=False, allow_blank=True)
    wallet_id = serializers.PrimaryKeyRelatedField(
        source="wallet",
        queryset=Wallet.objects.none(),
        required=False,
        allow_null=True,
    )

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
            "account_no",
            "debit_turnover",
            "payment_purpose",
            "vendor",
            "vendor_name",
            "wallet_id",
            "has_request",
            "has_paid_request",
            "matched_request_id",
            "request_required",
        ]
        read_only_fields = ["created_at", "created_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if tenant and "vendor" in self.fields:
            self.fields["vendor"].queryset = Vendor.objects.filter(tenant=tenant, kind=Vendor.KIND_TRANSFER)
        if tenant and "wallet_id" in self.fields:
            self.fields["wallet_id"].queryset = Wallet.objects.filter(
                tenant=tenant, wallet_type=Wallet.Type.BANK
            )

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        tenant = getattr(self.context.get("request"), "tenant", None)
        allow_missing_vendor = bool(self.context.get("allow_missing_vendor"))
        account_no = (attrs.pop("account_no", "") or "").strip()
        if account_no and tenant:
            resolved_vendor = (
                Vendor.objects.filter(
                    tenant=tenant,
                    kind=Vendor.KIND_TRANSFER,
                    account_number=account_no,
                )
                .order_by("id")
                .first()
            )
            if resolved_vendor is None:
                if not allow_missing_vendor:
                    raise serializers.ValidationError(
                        {"account_no": "No transfer vendor found for this account number in current tenant."}
                    )
            else:
                attrs["vendor"] = resolved_vendor

        vendor = attrs.get("vendor")
        if vendor is None and self.instance is not None:
            vendor = self.instance.vendor
        if vendor:
            if vendor.kind != Vendor.KIND_TRANSFER:
                raise serializers.ValidationError({"vendor": "Only vendors with type «перечисление» are allowed."})
            if tenant and vendor.tenant_id != tenant.id:
                raise serializers.ValidationError({"vendor": "Vendor must belong to this tenant."})
        elif not allow_missing_vendor:
            raise serializers.ValidationError({"vendor": "Vendor is required for bank expenses."})
        _apply_expense_calendar_from_doc_date(attrs, self.instance)
        if tenant:
            attrs = assign_wallet_for_bank_movement(instance=self.instance, tenant=tenant, attrs=attrs)
        return attrs

    def get_request_required(self, obj) -> bool:
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if not tenant:
            return True
        payment_type = Request.PAYMENT_TYPE_TRANSFER
        return is_request_required_for_expense(
            tenant=tenant,
            payment_type=payment_type,
            expense_obj=obj,
        )


class BankRevenueSerializer(serializers.ModelSerializer):
    doc_date = TashkentFlexibleDateField()
    process_date = TashkentFlexibleDateField()
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
                tenant=tenant, wallet_type=Wallet.Type.BANK
            )

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        attrs = super().validate(attrs)
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            attrs = assign_wallet_for_bank_movement(instance=self.instance, tenant=tenant, attrs=attrs)
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
            "wallet_id",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

