
import os
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from rest_framework import serializers

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.bank_expenses.serializers import BankExpenseSerializer, BankRevenueSerializer
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.cashier.serializers import CashExpenseSerializer, CashRevenueSerializer
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import CardExpenseSerializer, CardRevenueSerializer
from apps.modules.notes.models import Note
from apps.modules.requests.models import Approval, Request
from apps.modules.requests.serializers import PortalRequestSerializer, payment_type_to_vendor_kind
from apps.modules.vendors.models import Vendor
from apps.modules.vendors.serializers import VendorSerializer
from apps.tenants.models import TenantMembership, TenantUserRole
from apps.tenants.permissions import has_effective_module_access


class N8nRequestImportSerializer(PortalRequestSerializer):
    """Upsert by id; skips RequestFormConfig / payment_purpose whitelist."""

    id = serializers.IntegerField(required=True)

    class Meta(PortalRequestSerializer.Meta):
        read_only_fields = ["created_at", "created_by", "expense_link"]

    def validate(self, attrs):
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        actor = getattr(request_obj, "user", None)

        is_tenant_admin = bool(
            tenant
            and actor
            and getattr(actor, "is_authenticated", False)
            and TenantUserRole.objects.filter(
                tenant=tenant, user=actor, role=TenantUserRole.ROLE_ADMIN
            ).exists()
        )
        if not is_tenant_admin:
            attrs["requester"] = actor

        payment_type = attrs.get("payment_type")
        if payment_type is None and self.instance is not None:
            payment_type = self.instance.payment_type

        requester = attrs.get("requester")
        if requester is None and self.instance is not None:
            requester = self.instance.requester

        if requester is None:
            raise serializers.ValidationError({"requester": "Requester is required."})

        if not TenantMembership.objects.filter(tenant=tenant, user=requester, is_active=True).exists():
            raise serializers.ValidationError(
                {"requester": "Requester must be an active member of this tenant."}
            )

        if not TenantUserRole.objects.filter(
            tenant=tenant, user=requester, role=TenantUserRole.ROLE_REQUESTER
        ).exists():
            raise serializers.ValidationError(
                {"requester": "Requester must have role 'requester' in this tenant."}
            )

        vref = attrs.get("vendor_ref")
        if vref is None and self.instance is not None:
            vref = self.instance.vendor_ref
        if "vendor_ref" in attrs and attrs.get("vendor_ref") is None:
            vref = None
        if payment_type and vref:
            if vref.tenant_id != tenant.id:
                raise serializers.ValidationError({"vendor_ref": "Vendor must belong to this tenant."})
            if vref.kind != payment_type_to_vendor_kind(payment_type):
                raise serializers.ValidationError(
                    {"vendor_ref": "Vendor payment type does not match request payment type."}
                )
        if vref:
            attrs["vendor"] = vref.name
        elif "vendor_ref" in attrs and attrs.get("vendor_ref") is None:
            attrs["vendor"] = (attrs.get("vendor") or "") if attrs.get("vendor") is not None else ""

        # Convert incoming n8n `file_link` into Django-stored media.
        #
        # Contract:
        # - When creating: always download absolute http(s):// file_link into Django.
        # - When updating: only download if existing Request.file_link is empty.
        raw_file_link = attrs.get("file_link")
        if isinstance(raw_file_link, str):
            file_link = raw_file_link.strip()
        else:
            file_link = ""

        if file_link:
            is_abs = file_link.startswith("http://") or file_link.startswith("https://")
            if is_abs:
                existing = getattr(self.instance, "file_link", None) if self.instance is not None else None
                existing_str = str(existing or "").strip()
                should_convert = self.instance is None or not existing_str
                if should_convert:
                    token = os.getenv("N8N_TOKEN", "").strip()
                    if not token:
                        raise serializers.ValidationError({"file_link": "N8N_TOKEN is not configured."})

                    tenant_id = tenant.id if tenant else None
                    req_id = attrs.get("id") if attrs.get("id") is not None else getattr(self.instance, "id", None)
                    if not tenant_id or not req_id:
                        raise serializers.ValidationError(
                            {"file_link": "Cannot resolve tenant_id or request id for file storage."}
                        )

                    parsed = urlparse(file_link)
                    filename = os.path.basename(parsed.path) or "file"
                    filename = filename.replace("\x00", "").replace("/", "_").replace("\\", "_")

                    storage_rel_dir = f"requests/{tenant_id}/{req_id}"
                    storage_rel_path = f"{storage_rel_dir}/{filename}"

                    resp = requests.get(
                        file_link,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=30,
                    )
                    resp.raise_for_status()

                    # default_storage may rename on collisions; we persist returned name.
                    saved_name = default_storage.save(storage_rel_path, ContentFile(resp.content))
                    attrs["file_link"] = saved_name

        return attrs


class N8nApprovalImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=True)
    request = serializers.PrimaryKeyRelatedField(queryset=Request.objects.none())

    class Meta:
        model = Approval
        fields = [
            "id",
            "request",
            "approver_user",
            "approver_tg_id",
            "approver_tg_from_id",
            "message_id",
            "message_sent",
            "step",
            "step_type",
            "decision",
            "comment",
            "decided_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get("request")
        tenant = getattr(req, "tenant", None)
        if tenant:
            self.fields["request"].queryset = Request.objects.filter(tenant=tenant)


class N8nVendorImportSerializer(VendorSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(VendorSerializer.Meta):
        read_only_fields = ["tenant", "created_at", "created_by"]


class N8nCashExpenseImportSerializer(CashExpenseSerializer):
    id = serializers.IntegerField(required=True)

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if isinstance(data, Mapping):
            data = dict(data)
        return serializers.ModelSerializer.to_internal_value(self, data)

    class Meta(CashExpenseSerializer.Meta):
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


class N8nCashRevenueImportSerializer(CashRevenueSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(CashRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nPayrollLineImportSerializer(serializers.ModelSerializer):
    """Upsert payroll line by id; doc_id ties to PayrollDocument (auto-created)."""

    id = serializers.IntegerField(required=True)
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
        line_id = validated_data.pop("id")
        doc_id = validated_data.pop("doc_id")
        tenant = self.context["request"].tenant
        doc, _ = PayrollDocument.objects.get_or_create(tenant=tenant, doc_id=doc_id)
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
    id = serializers.IntegerField(required=True)

    class Meta(BankExpenseSerializer.Meta):
        read_only_fields = [
            "created_at",
            "created_by",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]


class N8nBankRevenueImportSerializer(BankRevenueSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(BankRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardExpenseImportSerializer(CardExpenseSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(CardExpenseSerializer.Meta):
        read_only_fields = ["created_at", "created_by"]


class N8nCardRevenueImportSerializer(CardRevenueSerializer):
    id = serializers.IntegerField(required=True)

    class Meta(CardRevenueSerializer.Meta):
        read_only_fields = ["created_at", "created_by", "bank_expense_exists"]


TARGET_TO_MODULE = {
    Note.TARGET_REQUEST: "requests",
    Note.TARGET_CASH: "cash",
    Note.TARGET_BANK: "bank",
}


class N8nNoteImportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=True)

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
