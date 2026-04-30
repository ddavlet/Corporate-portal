import logging

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.cashier.serializers import CashExpenseSerializer, CashRevenueSerializer
from apps.modules.wallets.models import CashRegister
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import CardExpenseSerializer, CardRevenueSerializer
from apps.modules.notes.models import Note
from apps.modules.investments.serializers import (
    InvestCompanySerializer,
    InvestPayoutScheduleSerializer,
    InvestReturnSerializer,
    ProjectInvestmentSerializer,
)
from apps.modules.requests.expense_refs import (
    expense_ref_target_for,
    resolve_request_expense_ref,
)
from apps.modules.requests.models import Approval, Request
from apps.modules.vendors.models import Vendor
from apps.modules.vendors.serializers import VendorSerializer
from apps.modules.clients_debt.serializers import ClientDebtSnapshotSerializer
from apps.tenants.permissions import has_effective_module_access
from apps.tenants.models import TenantMembership, TenantUserRole

User = get_user_model()
logger = logging.getLogger(__name__)


def _bind_cash_wallet_by_register_name(*, attrs: dict, tenant, instance) -> dict:
    """
    Optional n8n helper:
    allow `cash_register_name` in payload and map it to `wallet`.
    """
    raw_name = attrs.pop("cash_register_name", None)
    if raw_name is None:
        return attrs

    name = str(raw_name or "").strip()
    logger.info(
        "n8n cash register lookup started tenant_id=%s raw_name=%r normalized_name=%r",
        getattr(tenant, "id", None),
        raw_name,
        name,
    )
    if not name:
        raise serializers.ValidationError({"cash_register_name": "Название кассы не может быть пустым."})

    matches = list(
        CashRegister.objects.filter(tenant=tenant, name=name)
        .select_related("wallet")
        .order_by("id")[:2]
    )
    if not matches:
        available = list(
            CashRegister.objects.filter(tenant=tenant)
            .order_by("id")
            .values_list("id", "name")
        )
        logger.warning(
            "n8n cash register lookup failed tenant_id=%s normalized_name=%r available=%r",
            getattr(tenant, "id", None),
            name,
            available,
        )
        available_names = [row_name for _, row_name in available if str(row_name or "").strip()]
        details = (
            f"Касса с названием '{name}' не найдена."
            + (f" Доступные кассы: {', '.join(available_names)}." if available_names else "")
        )
        raise serializers.ValidationError({"cash_register_name": details})
    if len(matches) > 1:
        raise serializers.ValidationError(
            {"cash_register_name": "Найдено несколько касс с таким названием. Укажите wallet_id."}
        )

    reg = matches[0]
    wallet = getattr(reg, "wallet", None)
    if wallet is None:
        raise serializers.ValidationError({"cash_register_name": "Для выбранной кассы не найден wallet."})

    # Keep currency consistency when payload explicitly provides currency.
    payload_currency = attrs.get("currency")
    effective_currency = payload_currency
    if effective_currency is None and instance is not None:
        effective_currency = getattr(instance, "currency", None)
    if effective_currency and str(effective_currency).strip() != str(reg.currency).strip():
        raise serializers.ValidationError(
            {"cash_register_name": "Валюта кассы не совпадает с валютой операции."}
        )

    attrs["wallet"] = wallet
    return attrs


class N8nVendorImportSerializer(VendorSerializer):
    id = serializers.IntegerField(required=False)

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if isinstance(data, Mapping):
            data = dict(data)
            if "account_number" not in data and "account_no" in data:
                data["account_number"] = data.get("account_no")
        return serializers.ModelSerializer.to_internal_value(self, data)

    class Meta(VendorSerializer.Meta):
        read_only_fields = ["tenant", "created_at", "created_by"]


class N8nCashExpenseImportSerializer(CashExpenseSerializer):
    id = serializers.IntegerField(required=False)
    cash_register_name = serializers.CharField(required=False, allow_blank=True)

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if isinstance(data, Mapping):
            data = dict(data)
        return serializers.ModelSerializer.to_internal_value(self, data)

    class Meta(CashExpenseSerializer.Meta):
        fields = CashExpenseSerializer.Meta.fields + ["cash_register_name"]
        read_only_fields = [
            "expense_year",
            "expense_month",
            "expense_day",
            "created_at",
            "created_by",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]

    def validate(self, attrs):
        attrs = _bind_cash_wallet_by_register_name(
            attrs=attrs,
            tenant=getattr(self.context.get("request"), "tenant", None),
            instance=self.instance,
        )
        return super().validate(attrs)


class N8nCashRevenueImportSerializer(CashRevenueSerializer):
    id = serializers.IntegerField(required=False)
    cash_register_name = serializers.CharField(required=False, allow_blank=True)

    class Meta(CashRevenueSerializer.Meta):
        fields = CashRevenueSerializer.Meta.fields + ["cash_register_name"]
        read_only_fields = ["created_at", "created_by"]

    def validate(self, attrs):
        attrs = _bind_cash_wallet_by_register_name(
            attrs=attrs,
            tenant=getattr(self.context.get("request"), "tenant", None),
            instance=self.instance,
        )
        return super().validate(attrs)


class N8nPayrollLineImportSerializer(serializers.ModelSerializer):
    """Upsert payroll line by id; doc_id ties to PayrollDocument (auto-created)."""

    id = serializers.IntegerField(required=False)
    doc_id = serializers.CharField(write_only=True)

    class Meta:
        model = PayrollLine
        fields = [
            "id",
            "doc_id",
            "line_no",
            "employee",
            "item",
            "description",
            "sum",
            "days_plan",
            "days_fact",
            "period_start",
            "period_end",
            "approval",
        ]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["doc_id"] = instance.document.doc_id
        return ret

    def create(self, validated_data):
        line_id = validated_data.pop("id", None)
        doc_id = validated_data.pop("doc_id")
        tenant = self.context["request"].tenant
        doc, _ = PayrollDocument.objects.get_or_create(tenant=tenant, doc_id=doc_id)
        if line_id is None:
            return PayrollLine.objects.create(document=doc, **validated_data)
        return PayrollLine.objects.create(id=line_id, document=doc, **validated_data)

    def update(self, instance, validated_data):
        doc_id = validated_data.pop("doc_id", None)
        if doc_id is not None:
            tenant = self.context["request"].tenant
            doc, _ = PayrollDocument.objects.get_or_create(tenant=tenant, doc_id=doc_id)
            validated_data["document"] = doc
        validated_data.pop("id", None)
        return super().update(instance, validated_data)


class N8nBankExpenseImportSerializer(BankExpenseSerializer):
    id = serializers.IntegerField(required=False)
    vendor_name = serializers.CharField(required=False, allow_blank=True, write_only=True)
    account_name = serializers.CharField(required=False, allow_blank=True, write_only=True)
    counterparty = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs):
        tenant = getattr(self.context.get("request"), "tenant", None)
        self.context["allow_missing_vendor"] = True
        raw_account_no = attrs.get("account_no")
        account_no = str(raw_account_no or "").strip()
        vendor_name = str(attrs.pop("vendor_name", "") or "").strip()
        account_name = str(attrs.pop("account_name", "") or "").strip()
        counterparty = str(attrs.pop("counterparty", "") or "").strip()
        lookup_name = vendor_name or account_name or counterparty

        # When account_no is provided, let base BankExpenseSerializer resolve vendor by account.
        if attrs.get("vendor") is None and tenant and lookup_name and not account_no:
            matches = list(
                Vendor.objects.filter(
                    tenant=tenant,
                    kind=Vendor.KIND_TRANSFER,
                    name=lookup_name,
                )
                .order_by("id")[:2]
            )
            if not matches:
                raise serializers.ValidationError(
                    {"vendor_name": f"Transfer vendor with name '{lookup_name}' not found in current tenant."}
                )
            if len(matches) > 1:
                raise serializers.ValidationError(
                    {"vendor_name": f"Multiple transfer vendors found with name '{lookup_name}'."}
                )
            attrs["vendor"] = matches[0]
        return super().validate(attrs)

    class Meta(BankExpenseSerializer.Meta):
        fields = BankExpenseSerializer.Meta.fields + ["vendor_name", "account_name", "counterparty"]
        read_only_fields = [
            "created_at",
            "created_by",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]


class N8nBankRevenueImportSerializer(BankRevenueSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(BankRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardExpenseImportSerializer(CardExpenseSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(CardExpenseSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardRevenueImportSerializer(CardRevenueSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(CardRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by", "bank_expense_exists"]


class N8nClientDebtImportSerializer(ClientDebtSnapshotSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(ClientDebtSnapshotSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nInvestReturnImportSerializer(InvestReturnSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(InvestReturnSerializer.Meta):
        read_only_fields = ["tenant", "created_at", "last_edit_at", "created_by"]


class N8nInvestPayoutScheduleImportSerializer(InvestPayoutScheduleSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(InvestPayoutScheduleSerializer.Meta):
        read_only_fields = ["tenant", "created_at", "last_edit_at", "created_by"]


class N8nProjectInvestmentImportSerializer(ProjectInvestmentSerializer):
    id = serializers.IntegerField(required=False)

    class Meta(ProjectInvestmentSerializer.Meta):
        read_only_fields = ["tenant", "created_at", "last_edit_at", "created_by"]


class N8nInvestCompanyImportSerializer(InvestCompanySerializer):
    id = serializers.IntegerField(required=False)

    class Meta(InvestCompanySerializer.Meta):
        read_only_fields = ["tenant", "created_at", "last_edit_at", "created_by"]


class N8nRequestImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    requester = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    vendor_ref = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), required=False, allow_null=True)
    billing_date = serializers.DateField(required=False)
    description = serializers.CharField(allow_blank=True, required=False, default="")

    class Meta:
        model = Request
        fields = [
            "id",
            "company_payer",
            "category",
            "vendor",
            "vendor_ref",
            "title",
            "description",
            "amount",
            "currency",
            "payment_type",
            "urgency",
            "requester",
            "payment_purpose",
            "submitted_at",
            "status",
            "payed_at",
            "expense_id",
            "file_link",
            "expense_year",
            "expense_month",
            "expense_day",
            "billing_date",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            self.fields["vendor_ref"].queryset = Vendor.objects.filter(tenant=tenant)

    def validate_requester(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if value is None or tenant is None:
            return value
        is_member = TenantMembership.objects.filter(tenant=tenant, user=value, is_active=True).exists()
        roles = list(
            TenantUserRole.objects.filter(tenant=tenant, user=value).values_list("role", flat=True).distinct()
        )
        if not is_member:
            raise serializers.ValidationError(
                (
                    f"Requester must be an active tenant member. "
                    f"tenant_id={tenant.id}, tenant_subdomain={tenant.subdomain}, "
                    f"requester_id={value.id}, requester_username={value.username}, roles={roles}"
                )
            )
        if not TenantUserRole.objects.filter(
            tenant=tenant, user=value, role=TenantUserRole.ROLE_REQUESTER
        ).exists():
            raise serializers.ValidationError(
                (
                    f"Requester must have role 'requester' in this tenant. "
                    f"tenant_id={tenant.id}, tenant_subdomain={tenant.subdomain}, "
                    f"requester_id={value.id}, requester_username={value.username}, roles={roles}"
                )
            )
        return value

    def validate_vendor_ref(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if value is None or tenant is None:
            return value
        if value.tenant_id != tenant.id:
            raise serializers.ValidationError("Vendor must belong to this tenant.")
        return value

    def validate(self, attrs):
        tenant = getattr(self.context.get("request"), "tenant", None)
        vendor_ref = attrs.get("vendor_ref")
        payment_type = attrs.get("payment_type")
        if self.instance is not None:
            if vendor_ref is None and "vendor_ref" not in attrs:
                vendor_ref = self.instance.vendor_ref
            if payment_type is None:
                payment_type = self.instance.payment_type
        if vendor_ref and payment_type:
            expected_kind = Vendor.KIND_CASH if payment_type == Request.PAYMENT_TYPE_CASH else Vendor.KIND_TRANSFER
            if vendor_ref.kind != expected_kind:
                raise serializers.ValidationError(
                    {"vendor_ref": "Vendor payment type does not match request payment type."}
                )
            attrs["vendor"] = vendor_ref.name
        if self.instance is None and "billing_date" not in attrs:
            raise serializers.ValidationError({"billing_date": "This field is required."})
        if self.instance is None and "requester" not in attrs:
            raise serializers.ValidationError({"requester": "This field is required."})
        effective_payment_type = attrs.get("payment_type")
        if effective_payment_type is None and self.instance is not None:
            effective_payment_type = self.instance.payment_type
        effective_category = attrs.get("category")
        if effective_category is None and self.instance is not None:
            effective_category = self.instance.category
        expense_id_val = attrs.get("expense_id")
        if expense_id_val is None and self.instance is not None and "expense_id" not in attrs:
            expense_id_val = self.instance.expense_id
        effective_expense_year = attrs.get("expense_year")
        if effective_expense_year is None and self.instance is not None:
            effective_expense_year = self.instance.expense_year
        eid = str(expense_id_val or "").strip()
        if not eid:
            attrs["expense_ref_id"] = None
            attrs["expense_ref_target"] = None
        else:
            ref, normalized_expense_id = resolve_request_expense_ref(
                tenant=tenant,
                payment_type=effective_payment_type,
                category=effective_category,
                expense_id_raw=expense_id_val,
                expense_year=effective_expense_year,
            )
            tgt = expense_ref_target_for(payment_type=effective_payment_type, category=effective_category) if ref else None
            attrs["expense_ref_id"] = ref
            attrs["expense_ref_target"] = tgt
            if normalized_expense_id and effective_payment_type == Request.PAYMENT_TYPE_CASH:
                attrs["expense_id"] = normalized_expense_id
        return attrs


class N8nApprovalImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    approver_user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    request = serializers.PrimaryKeyRelatedField(queryset=Request.objects.all())

    class Meta:
        model = Approval
        fields = [
            "id",
            "request",
            "approver_user",
            "approver_recipient_id",
            "approver_external_user_id",
            "gateway_message_id",
            "message_sent",
            "message_sent_at",
            "step",
            "step_type",
            "decision",
            "comment",
            "decided_at",
            "resend_batch_id",
            "resend_key",
            "replaced_approval",
        ]
        extra_kwargs = {
            "step": {"required": False},
            "step_type": {"required": False},
            "decision": {"required": False},
            "message_sent": {"required": False},
        }

    def validate_request(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant and value.tenant_id != tenant.id:
            raise serializers.ValidationError("Request must belong to this tenant.")
        return value

    def validate_approver_user(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if value is None or tenant is None:
            return value
        is_member = TenantMembership.objects.filter(tenant=tenant, user=value, is_active=True).exists()
        roles = list(
            TenantUserRole.objects.filter(tenant=tenant, user=value).values_list("role", flat=True).distinct()
        )
        if not is_member:
            raise serializers.ValidationError(
                (
                    f"Approver user must be an active tenant member. "
                    f"tenant_id={tenant.id}, tenant_subdomain={tenant.subdomain}, "
                    f"approver_user_id={value.id}, approver_username={value.username}, roles={roles}"
                )
            )
        return value

    def validate(self, attrs):
        if self.instance is None and "approver_user" not in attrs:
            raise serializers.ValidationError({"approver_user": "This field is required."})
        return attrs


TARGET_TO_MODULE = {
    Note.TARGET_REQUEST: "requests",
    Note.TARGET_CASH: "cash",
    Note.TARGET_BANK: "bank",
}


class N8nNoteImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Note
        fields = [
            "id",
            "recipient_user",
            "target_type",
            "target_id",
            "message",
            "delivery_status",
            "delivery_error",
            "sent_at",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["created_at", "created_by"]

    def validate_recipient_user(self, value):
        request = self.context["request"]
        tenant = request.tenant
        is_member = value.tenantmembership_set.filter(tenant=tenant, is_active=True).exists()
        if not is_member:
            raise serializers.ValidationError("Recipient must be an active tenant member.")
        if not value.telegram_chat_id:
            raise serializers.ValidationError("Recipient has no telegram_chat_id.")
        return value

    def validate(self, attrs):
        request = self.context["request"]
        tenant = request.tenant
        user = request.user
        target_type = attrs.get("target_type")
        target_id = attrs.get("target_id")
        if self.instance is not None:
            target_type = target_type if target_type is not None else self.instance.target_type
            target_id = target_id if target_id is not None else self.instance.target_id
        module_key = TARGET_TO_MODULE.get(target_type)
        if not module_key:
            raise serializers.ValidationError({"target_type": "Unsupported target type."})
        if not has_effective_module_access(user=user, tenant=tenant, module_key=module_key):
            raise serializers.ValidationError({"target_type": "No access to target module."})
        if target_type == Note.TARGET_REQUEST:
            exists = Request.objects.filter(tenant=tenant, id=target_id).exists()
        elif target_type == Note.TARGET_CASH:
            exists = CashExpense.objects.filter(tenant=tenant, id=target_id).exists()
        else:
            exists = BankExpense.objects.filter(tenant=tenant, id=target_id).exists()
        if not exists:
            raise serializers.ValidationError({"target_id": "Target entry not found in this tenant."})
        return attrs
