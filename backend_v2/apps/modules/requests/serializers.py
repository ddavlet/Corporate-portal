from rest_framework import serializers
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import connection
from urllib.parse import quote

from apps.modules.requests.models import (
    Approval,
    Request,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestFormPaymentTypeVendor,
    RequestPaymentPurposeConfig,
)
from apps.modules.vendors.models import Vendor
from apps.modules.cashier.models import CashExpense
from apps.modules.bank_expenses.models import BankExpense
from apps.tenants.permissions import has_effective_module_access
from apps.tenants.models import TenantMembership, TenantUserRole

User = get_user_model()


def payment_type_to_vendor_kind(payment_type: str) -> str:
    if payment_type == Request.PAYMENT_TYPE_CASH:
        return Vendor.KIND_CASH
    return Vendor.KIND_TRANSFER


class PortalRequestSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    expense_link = serializers.SerializerMethodField()
    requester = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True)
    requester_username = serializers.SerializerMethodField()
    vendor_ref = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), allow_null=True, required=False)

    class Meta:
        model = Request
        fields = [
            "id",
            "created_at",
            "created_by",
            "expense_id",
            "expense_link",
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
            "requester_username",
            "payment_purpose",
            "submitted_at",
            "status",
            "payed_at",
            "file_link",
            "expense_year",
            "expense_month",
            "expense_day",
            "billing_date",
        ]
        read_only_fields = ["expense_link", "created_at", "created_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if tenant and "vendor_ref" in self.fields:
            self.fields["vendor_ref"].queryset = Vendor.objects.filter(tenant=tenant)

    def validate(self, attrs):
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        actor = getattr(request_obj, "user", None)

        is_tenant_admin = bool(
            tenant
            and actor
            and getattr(actor, "is_authenticated", False)
            and TenantUserRole.objects.filter(
                tenant=tenant,
                user=actor,
                role=TenantUserRole.ROLE_ADMIN,
            ).exists()
        )

        # Не-админы всегда заявитель = кто создаёт заявку (поле requester из запроса игнорируется).
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

        has_membership = TenantMembership.objects.filter(
            tenant=tenant, user=requester, is_active=True
        ).exists()
        if not has_membership:
            raise serializers.ValidationError(
                {"requester": "Requester must be an active member of this tenant."}
            )

        has_requester_role = TenantUserRole.objects.filter(
            tenant=tenant, user=requester, role=TenantUserRole.ROLE_REQUESTER
        ).exists()
        if not has_requester_role:
            raise serializers.ValidationError(
                {"requester": "Requester must have role 'requester' in this tenant."}
            )

        # Adaptive request-form config validation (tenant-level, optional).
        cfg = RequestFormConfig.objects.filter(tenant=tenant).first()
        if cfg and payment_type:
            pt_cfg = RequestFormPaymentTypeConfig.objects.filter(
                config=cfg,
                payment_type=payment_type,
            ).first()
            if not pt_cfg or not pt_cfg.is_enabled:
                raise serializers.ValidationError(
                    {"payment_type": "This payment type is disabled by request form configuration."}
                )

            # Requester must be in configured subset if subset is defined.
            allowed_requester_ids = list(
                RequestFormPaymentTypeRequester.objects.filter(payment_type_config=pt_cfg).values_list(
                    "user_id", flat=True
                )
            )
            if allowed_requester_ids and requester.id not in set(allowed_requester_ids):
                if not is_tenant_admin:
                    raise serializers.ValidationError(
                        {"requester": "Requester is not allowed for this payment type."}
                    )

            expected_kind = payment_type_to_vendor_kind(payment_type)
            vendor_ref = attrs.get("vendor_ref")
            if vendor_ref is None and "vendor_ref" not in attrs and self.instance is not None:
                vendor_ref = self.instance.vendor_ref

            vendor_value = attrs.get("vendor")
            if vendor_value is None and self.instance is not None:
                vendor_value = self.instance.vendor
            vendor_value = str(vendor_value or "").strip()
            allowed_vendor_ids = list(
                RequestFormPaymentTypeVendor.objects.filter(payment_type_config=pt_cfg).values_list(
                    "vendor_id", flat=True
                )
            )
            if allowed_vendor_ids:
                vref = vendor_ref
                if not vref and vendor_value:
                    vref = Vendor.objects.filter(
                        tenant=tenant, name=vendor_value, kind=expected_kind
                    ).first()
                    if vref:
                        attrs["vendor_ref"] = vref
                        vendor_ref = vref
                if vendor_ref or vendor_value:
                    if not vendor_ref:
                        raise serializers.ValidationError(
                            {"vendor_ref": "Select a vendor from the directory or provide a valid vendor."}
                        )
                    if vendor_ref.id not in set(allowed_vendor_ids):
                        raise serializers.ValidationError(
                            {"vendor_ref": "Vendor is not allowed for this payment type."}
                        )

            # Payment purpose restrictions + auto category.
            purpose_value = attrs.get("payment_purpose")
            if purpose_value is None and self.instance is not None:
                purpose_value = self.instance.payment_purpose
            purpose_value = str(purpose_value or "").strip()

            purpose_rows = list(
                RequestPaymentPurposeConfig.objects.filter(payment_type_config=pt_cfg, is_active=True)
            )
            if purpose_rows:
                if not purpose_value:
                    raise serializers.ValidationError({"payment_purpose": "Payment purpose is required."})
                matched = next((p for p in purpose_rows if p.name == purpose_value), None)
                if not matched:
                    raise serializers.ValidationError(
                        {"payment_purpose": "Payment purpose is not allowed for this payment type."}
                    )
                # Category is derived from purpose mapping.
                attrs["category"] = matched.category

        vref = attrs.get("vendor_ref")
        if vref is None and "vendor_ref" not in attrs and self.instance is not None:
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

        return attrs

    def get_requester_username(self, obj):
        return obj.requester.username if obj.requester else None

    def get_expense_link(self, obj):
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None)
        user = getattr(request, "user", None)

        if not getattr(obj, "expense_id", None):
            return None
        raw_expense_id = str(obj.expense_id).strip()

        # expense_id is stored as varchar(20) and is expected to be numeric for local modules.
        try:
            numeric_id = int(raw_expense_id)
        except (TypeError, ValueError):
            numeric_id = None

        # If cash module is effectively enabled, resolve `expense_id` by PK or by external_id.
        if has_effective_module_access(user=user, tenant=tenant, module_key="cash"):
            cash_expense = CashExpense.objects.filter(tenant=tenant, external_id=raw_expense_id).first()
            if not cash_expense and numeric_id is not None:
                cash_expense = CashExpense.objects.filter(tenant=tenant, id=numeric_id).first()
            if cash_expense:
                rel = reverse("cash-expenses-detail", kwargs={"pk": cash_expense.id})
                url = request.build_absolute_uri(rel) if request else rel
                return {
                    "module": "cash",
                    "expense_type": "cash",
                    "id": cash_expense.id,
                    "url": url,
                }

        # If cashier didn't match, try bank module (independent via module toggles).
        if numeric_id is not None and has_effective_module_access(user=user, tenant=tenant, module_key="bank"):
            bank_expense = BankExpense.objects.filter(tenant=tenant, id=numeric_id).first()
            if bank_expense:
                rel = reverse("bank-expenses-detail", kwargs={"pk": bank_expense.id})
                url = request.build_absolute_uri(rel) if request else rel
                return {
                    "module": "bank",
                    "expense_type": "bank",
                    "id": bank_expense.id,
                    "url": url,
                }

        # Fallback: only return raw external id (frontend can decide how to render).
        return {"module": "external", "expense_type": "unknown", "id": raw_expense_id, "url": None}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        file_link = data.get("file_link")
        request = self.context.get("request")
        if file_link and request:
            gateway_rel = f"/api/files/gateway/?path={quote(str(file_link), safe='')}"
            data["file_link"] = request.build_absolute_uri(gateway_rel)
        return data


class ApprovalSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    approver_username = serializers.SerializerMethodField()

    class Meta:
        model = Approval
        fields = [
            "id",
            "step",
            "step_type",
            "decision",
            "comment",
            "decided_at",
            "approver_user",
            "approver_username",
            "approver_tg_id",
            "message_id",
            "message_sent",
        ]
        read_only_fields = ["approver_username"]

    def get_approver_username(self, obj):
        return getattr(obj.approver_user, "username", None)


class PortalRequestDetailSerializer(PortalRequestSerializer):
    approvals = serializers.SerializerMethodField()

    class Meta(PortalRequestSerializer.Meta):
        fields = PortalRequestSerializer.Meta.fields + ["approvals"]

    def get_approvals(self, obj):
        # Some environments may not have applied approvals-table migration yet.
        if Approval._meta.db_table not in connection.introspection.table_names():
            return []
        queryset = Approval.objects.filter(request=obj).select_related("approver_user").order_by("step", "id")
        return ApprovalSerializer(queryset, many=True).data


class RequestPaymentPurposeConfigItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    name = serializers.CharField()
    category = serializers.CharField()
    is_active = serializers.BooleanField(required=False, default=True)


class RequestFormPaymentTypeConfigSerializer(serializers.Serializer):
    payment_type = serializers.ChoiceField(choices=Request.PAYMENT_TYPE_CHOICES)
    is_enabled = serializers.BooleanField(required=False, default=True)
    requester_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
    )
    vendor_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
    )
    payment_purposes = serializers.ListField(
        child=RequestPaymentPurposeConfigItemSerializer(),
        required=False,
        default=list,
    )
    default_title = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    default_description = serializers.CharField(required=False, allow_blank=True, default="")
    default_amount = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=12,
        decimal_places=2,
        default=None,
    )
    default_currency = serializers.ChoiceField(
        choices=Request.CURRENCY_CHOICES, required=False, default=Request.CURRENCY_UZS
    )
    default_urgency = serializers.ChoiceField(
        choices=Request.URGENCY_CHOICES, required=False, default=Request.URGENCY_NORMAL
    )
    default_billing_days_offset = serializers.IntegerField(
        required=False, default=0, min_value=-3650, max_value=3650
    )
    default_payment_purpose = serializers.CharField(
        required=False, allow_blank=True, max_length=200, default=""
    )
    default_vendor_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class RequestFormConfigPayloadSerializer(serializers.Serializer):
    payment_types = serializers.ListField(child=RequestFormPaymentTypeConfigSerializer())


class RequesterCandidateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()


class VendorCandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ["id", "kind", "name", "inn", "account_number"]


def build_request_form_config_response(*, tenant) -> dict:
    """
    Returns config plus candidates needed by admin UI.
    """
    cfg = RequestFormConfig.objects.filter(tenant=tenant).first()

    # Candidates: all active tenant members with requester role.
    requester_user_ids = list(
        TenantUserRole.objects.filter(
            tenant=tenant,
            role=TenantUserRole.ROLE_REQUESTER,
        ).values_list("user_id", flat=True)
    )
    requester_candidates = User.objects.filter(id__in=requester_user_ids).order_by("username")

    vendor_candidates = Vendor.objects.filter(tenant=tenant).order_by("name")

    # "Predefined categories" source (current codebase stores category as text).
    categories_from_requests = (
        Request.objects.filter(tenant=tenant)
        .exclude(category="")
        .values_list("category", flat=True)
        .distinct()
    )
    categories_from_purposes = (
        RequestPaymentPurposeConfig.objects.filter(payment_type_config__config__tenant=tenant)
        .exclude(category="")
        .values_list("category", flat=True)
        .distinct()
    )
    categories = sorted({*list(categories_from_requests), *list(categories_from_purposes)})

    payment_type_rows: list[dict] = []
    if cfg:
        pt_qs = (
            RequestFormPaymentTypeConfig.objects.filter(config=cfg)
            .prefetch_related("allowed_requesters", "allowed_vendors", "payment_purposes")
            .order_by("payment_type")
        )
        for pt in pt_qs:
            amt = pt.default_amount
            payment_type_rows.append(
                {
                    "payment_type": pt.payment_type,
                    "is_enabled": pt.is_enabled,
                    "requester_ids": list(pt.allowed_requesters.values_list("user_id", flat=True)),
                    "vendor_ids": list(pt.allowed_vendors.values_list("vendor_id", flat=True)),
                    "payment_purposes": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "category": p.category,
                            "is_active": p.is_active,
                        }
                        for p in pt.payment_purposes.all().order_by("name", "id")
                    ],
                    "default_title": pt.default_title,
                    "default_description": pt.default_description,
                    "default_amount": str(amt) if amt is not None else None,
                    "default_currency": pt.default_currency,
                    "default_urgency": pt.default_urgency,
                    "default_billing_days_offset": pt.default_billing_days_offset,
                    "default_payment_purpose": pt.default_payment_purpose,
                    "default_vendor_id": pt.default_vendor_id,
                }
            )

    return {
        "payment_types": payment_type_rows,
        "requester_candidates": RequesterCandidateSerializer(
            requester_candidates, many=True
        ).data,
        "vendor_candidates": VendorCandidateSerializer(vendor_candidates, many=True).data,
        "category_candidates": categories,
    }

