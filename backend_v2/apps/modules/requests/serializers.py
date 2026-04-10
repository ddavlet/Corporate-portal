from datetime import date
from decimal import Decimal

from rest_framework import serializers
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from urllib.parse import quote

from apps.modules.requests.models import (
    Approval,
    Request,
    UserRequestApproval,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestFormPaymentTypeVendor,
    RequestPaymentPurposeConfig,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepConfig,
    RequestApprovalStepApproverConfig,
    RequestCategory,
    AutoRequestTemplate,
)
from apps.modules.vendors.models import Vendor
from apps.modules.cashier.models import CashExpense
from apps.modules.bank_expenses.models import BankExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.payroll.constants import MODULE_KEY as PAYROLL_MODULE_KEY, SALARY_CATEGORY
from apps.modules.payroll.models import PayrollDocument
from apps.modules.requests.expense_refs import (
    expense_ref_target_for,
    maybe_persist_request_expense_ref,
    try_resolve_request_expense_ref_id,
)
from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.tenants.permissions import has_effective_module_access
from apps.tenants.models import TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()
_username_validator = UnicodeUsernameValidator()


def _display_user_name(user) -> str | None:
    if not user:
        return None
    full = (getattr(user, "full_name", "") or "").strip()
    return full or getattr(user, "username", None)


def payment_type_to_vendor_kind(payment_type: str) -> str:
    if payment_type == Request.PAYMENT_TYPE_CASH:
        return Vendor.KIND_CASH
    return Vendor.KIND_TRANSFER


def payment_type_to_create_module_key(payment_type: str) -> str | None:
    if payment_type == Request.PAYMENT_TYPE_CASH:
        return "cash"
    if payment_type in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        return "bank"
    if payment_type == Request.PAYMENT_TYPE_CARD:
        return "corporate_card"
    return None


def payment_action_mode_choices_for_payment_type(*, tenant, payment_type: str) -> list[str]:
    options = [
        RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK,
        RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
    ]
    module_key = payment_type_to_create_module_key(payment_type)
    if module_key and TenantModuleConfig.objects.filter(
        tenant=tenant,
        module_key=module_key,
        is_enabled=True,
    ).exists():
        options.append(RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE)
    return options


class PortalRequestSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    expense_link = serializers.SerializerMethodField()
    # For non-admins we always derive `requester` from `request.user` in `validate()`.
    # So `requester` must be optional at serializer level.
    requester = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True, required=False)
    requester_username = serializers.SerializerMethodField()
    vendor_ref = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), allow_null=True, required=False)
    # `accounts/User` sends empty descriptions from UI/tests; model does not set `blank=True`,
    # so we allow blank explicitly at serializer level.
    description = serializers.CharField(allow_blank=True, required=False, default="")

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
            "amortization_months",
            "amortization_start_date",
        ]
        read_only_fields = ["expense_link", "created_at", "created_by", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if tenant and "vendor_ref" in self.fields:
            self.fields["vendor_ref"].queryset = Vendor.objects.filter(tenant=tenant)

    def validate(self, attrs):
        reject_client_pk_on_create(self)
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
            roles = list(
                TenantUserRole.objects.filter(tenant=tenant, user=requester)
                .values_list("role", flat=True)
                .distinct()
            )
            raise serializers.ValidationError(
                {
                    "requester": (
                        "Requester must have role 'requester' in this tenant. "
                        f"tenant_id={tenant.id}, tenant_subdomain={tenant.subdomain}, "
                        f"requester_id={requester.id}, requester_username={requester.username}, roles={roles}"
                    )
                }
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

            company_payer = attrs.get("company_payer")
            if company_payer is None and self.instance is not None:
                company_payer = self.instance.company_payer
            if not str(company_payer or "").strip() and pt_cfg.default_company_payer:
                attrs["company_payer"] = pt_cfg.default_company_payer

            # Requester must be in configured subset if subset is defined.
            allowed_requester_ids = list(
                RequestFormPaymentTypeRequester.objects.filter(payment_type_config=pt_cfg).values_list(
                    "user_id", flat=True
                )
            )
            if allowed_requester_ids and requester.id not in set(allowed_requester_ids):
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

        effective_pt = attrs.get("payment_type")
        if effective_pt is None and self.instance is not None:
            effective_pt = self.instance.payment_type
        effective_cat = attrs.get("category")
        if effective_cat is None and self.instance is not None:
            effective_cat = self.instance.category
        expense_id_val = attrs.get("expense_id")
        if expense_id_val is None and self.instance is not None and "expense_id" not in attrs:
            expense_id_val = self.instance.expense_id
        elif "expense_id" in attrs:
            expense_id_val = attrs.get("expense_id")
        eid = str(expense_id_val or "").strip()
        effective_expense_year = attrs.get("expense_year")
        if effective_expense_year is None and self.instance is not None:
            effective_expense_year = self.instance.expense_year
        if not eid:
            attrs["expense_ref_id"] = None
            attrs["expense_ref_target"] = None
        else:
            ref = try_resolve_request_expense_ref_id(
                tenant=tenant,
                payment_type=effective_pt,
                category=effective_cat,
                expense_id_raw=eid,
                expense_year=effective_expense_year,
            )
            tgt = expense_ref_target_for(payment_type=effective_pt, category=effective_cat) if ref else None
            attrs["expense_ref_id"] = ref
            attrs["expense_ref_target"] = tgt

        if self.context.get("submit_for_approval"):
            amt = attrs.get("amount")
            if amt is None and self.instance is not None:
                amt = self.instance.amount
            try:
                dec = Decimal(str(amt)) if amt is not None else Decimal("0")
            except Exception:
                dec = Decimal("0")
            if dec <= 0:
                raise serializers.ValidationError(
                    {"amount": "Amount must be greater than zero to submit for approval."}
                )

        billing_date = attrs.get("billing_date")
        if billing_date is None and self.instance is not None:
            billing_date = self.instance.billing_date
        if isinstance(billing_date, date):
            attrs["amortization_start_date"] = billing_date.replace(day=1)

        return attrs

    def get_requester_username(self, obj):
        return _display_user_name(obj.requester)

    def get_expense_link(self, obj):
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None)
        user = getattr(request, "user", None)

        raw = str(getattr(obj, "expense_id", None) or "").strip()
        ref_id = None
        if tenant:
            ref_id = maybe_persist_request_expense_ref(request_obj=obj, tenant=tenant)
        else:
            ref_id = obj.expense_ref_id or None

        pt = obj.payment_type

        # Наличные + зарплатная категория + модуль начислений: связь с документом ЗП по doc_id (не касса).
        if ref_id is not None and pt == Request.PAYMENT_TYPE_CASH and (obj.category or "").strip() == SALARY_CATEGORY:
            if has_effective_module_access(user=user, tenant=tenant, module_key=PAYROLL_MODULE_KEY):
                payroll_doc = PayrollDocument.objects.filter(tenant=tenant, id=ref_id).first()
                if payroll_doc:
                    rel = reverse("payroll-documents-detail", kwargs={"pk": payroll_doc.pk})
                    url = request.build_absolute_uri(rel) if request else rel
                    return {
                        "module": "payroll",
                        "expense_type": "payroll",
                        "id": payroll_doc.pk,
                        "doc_id": payroll_doc.doc_id,
                        "url": url,
                    }

        if ref_id is not None and pt == Request.PAYMENT_TYPE_CASH and has_effective_module_access(
            user=user, tenant=tenant, module_key="cash"
        ):
            cash_expense = CashExpense.objects.filter(tenant=tenant, id=ref_id).first()
            if cash_expense:
                rel = reverse("cash-expenses-detail", kwargs={"pk": cash_expense.id})
                url = request.build_absolute_uri(rel) if request else rel
                return {
                    "module": "cash",
                    "expense_type": "cash",
                    "id": cash_expense.id,
                    "url": url,
                }

        if ref_id is not None and pt in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP) and has_effective_module_access(
            user=user, tenant=tenant, module_key="bank"
        ):
            bank_expense = BankExpense.objects.filter(tenant=tenant, id=ref_id).first()
            if bank_expense:
                rel = reverse("bank-expenses-detail", kwargs={"pk": bank_expense.id})
                url = request.build_absolute_uri(rel) if request else rel
                return {
                    "module": "bank",
                    "expense_type": "bank",
                    "id": bank_expense.id,
                    "url": url,
                }

        if ref_id is not None and pt == Request.PAYMENT_TYPE_CARD and has_effective_module_access(
            user=user, tenant=tenant, module_key="corporate_card"
        ):
            card_expense = CardExpense.objects.filter(tenant=tenant, id=ref_id).first()
            if card_expense:
                rel = reverse("corporate-card-expenses-detail", kwargs={"pk": card_expense.id})
                url = request.build_absolute_uri(rel) if request else rel
                return {
                    "module": "corporate_card",
                    "expense_type": "card",
                    "id": card_expense.id,
                    "url": url,
                }

        if raw:
            return {"module": "external", "expense_type": "unknown", "id": raw, "url": None}
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        file_link = data.get("file_link")
        request = self.context.get("request")
        if file_link and request:
            raw = str(file_link).strip()
            if not raw:
                return data

            # If the DB record already stores our backend endpoints, keep it as-is.
            if "/api/files/gateway/" in raw or "/api/files/download/" in raw:
                data["file_link"] = (
                    raw
                    if raw.startswith("http://") or raw.startswith("https://")
                    else request.build_absolute_uri(raw)
                )
                return data

            # Backward compatibility:
            # - absolute URLs (from N8N) go through the gateway
            # - storage-relative paths (we will store as `requests/<...>`) go through download
            if raw.startswith("http://") or raw.startswith("https://"):
                gateway_rel = f"/api/files/gateway/?path={quote(raw, safe='')}"
                data["file_link"] = request.build_absolute_uri(gateway_rel)
            else:
                download_rel = f"/api/files/download/?path={quote(raw, safe='')}"
                data["file_link"] = request.build_absolute_uri(download_rel)
        return data


class ApprovalSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    approver_username = serializers.SerializerMethodField()
    payment_action_mode = serializers.SerializerMethodField()
    payment_webapp_url = serializers.SerializerMethodField()

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        return attrs

    class Meta:
        model = Approval
        fields = [
            "id",
            "step",
            "step_type",
            "payment_action_mode",
            "payment_webapp_url",
            "decision",
            "comment",
            "decided_at",
            "approver_user",
            "approver_username",
            "approver_tg_id",
            "approver_tg_from_id",
            "message_id",
            "message_sent",
            "message_sent_at",
        ]
        read_only_fields = ["approver_username"]

    def get_approver_username(self, obj):
        return _display_user_name(getattr(obj, "approver_user", None))

    def _get_payment_step_cfg(self, obj):
        if getattr(obj, "step_type", None) != Approval.STEP_TYPE_PAYMENT:
            return None
        req = getattr(obj, "request", None)
        if req is None:
            req = Request.objects.filter(pk=obj.request_id).only("tenant_id", "payment_type").first()
        if req is None:
            return None
        cache = self.context.setdefault("_approval_step_cfg_cache", {})
        key = (req.tenant_id, req.payment_type, obj.step, obj.step_type)
        if key in cache:
            return cache[key]
        cfg = (
            RequestApprovalStepConfig.objects.filter(
                payment_type_config__config__tenant_id=req.tenant_id,
                payment_type_config__payment_type=req.payment_type,
                step=obj.step,
                step_type=obj.step_type,
            )
            .order_by("id")
            .first()
        )
        cache[key] = cfg
        return cfg

    def get_payment_action_mode(self, obj):
        cfg = self._get_payment_step_cfg(obj)
        return cfg.payment_action_mode if cfg else None

    def get_payment_webapp_url(self, obj):
        cfg = self._get_payment_step_cfg(obj)
        return (cfg.payment_webapp_url or "") if cfg else ""


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


class MyApprovalsRequestSummarySerializer(serializers.ModelSerializer):
    requester_username = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = [
            "id",
            "title",
            "vendor",
            "category",
            "amount",
            "currency",
            "payment_type",
            "urgency",
            "status",
            "submitted_at",
            "billing_date",
            "requester",
            "requester_username",
        ]
        read_only_fields = fields

    def get_requester_username(self, obj):
        return _display_user_name(getattr(obj, "requester", None)) if obj.requester_id else None


class UserRequestApprovalStepSerializer(serializers.ModelSerializer):
    payment_action_mode = serializers.SerializerMethodField()

    class Meta:
        model = UserRequestApproval
        fields = ["id", "step", "step_type", "payment_action_mode", "decision", "comment", "decided_at"]

    def get_payment_action_mode(self, obj):
        if getattr(obj, "step_type", None) != Approval.STEP_TYPE_PAYMENT:
            return None
        req = getattr(obj, "request", None)
        if req is None:
            return None
        cache = self.context.setdefault("_user_approval_step_cfg_cache", {})
        key = (req.tenant_id, req.payment_type, obj.step, obj.step_type)
        if key in cache:
            cfg = cache[key]
        else:
            cfg = (
                RequestApprovalStepConfig.objects.filter(
                    payment_type_config__config__tenant_id=req.tenant_id,
                    payment_type_config__payment_type=req.payment_type,
                    step=obj.step,
                    step_type=obj.step_type,
                )
                .order_by("id")
                .first()
            )
            cache[key] = cfg
        return cfg.payment_action_mode if cfg else None


class ApprovalFullContextSerializer(serializers.Serializer):
    request = PortalRequestDetailSerializer()
    trigger_approval = ApprovalSerializer(allow_null=True)
    approvals = ApprovalSerializer(many=True)


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
    default_company_payer = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
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
    category_candidates = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
    )


class CreateTenantRequesterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    full_name = serializers.CharField(max_length=255)
    telegram_chat_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    telegram_from_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate_username(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Username is required.")
        try:
            _username_validator(cleaned)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0] if exc.messages else "Enter a valid username.") from exc
        return cleaned

    def validate_full_name(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Full name is required.")
        return cleaned


class RequesterCandidateSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username"]

    def get_username(self, obj):
        return _display_user_name(obj)


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

    categories = list(
        RequestCategory.objects.filter(tenant=tenant, is_active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )

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
                    "default_company_payer": pt.default_company_payer,
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


class RequestApprovalStepPayloadSerializer(serializers.Serializer):
    step = serializers.IntegerField()
    step_type = serializers.ChoiceField(choices=Approval.STEP_TYPE_CHOICES)
    is_enabled = serializers.BooleanField(required=False, default=True)
    approver_user_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    payment_action_mode = serializers.ChoiceField(
        choices=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CHOICES,
        required=False,
        default=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK,
    )
    payment_webapp_url = serializers.CharField(required=False, allow_blank=True, default="")


class RequestApprovalPaymentTypePayloadSerializer(serializers.Serializer):
    payment_type = serializers.ChoiceField(choices=Request.PAYMENT_TYPE_CHOICES)
    is_enabled = serializers.BooleanField(required=False, default=True)
    steps = serializers.ListField(child=RequestApprovalStepPayloadSerializer(), required=False, default=list)


class RequestApprovalConfigPayloadSerializer(serializers.Serializer):
    class IntegrationSettingsPayloadSerializer(serializers.Serializer):
        telegram_approvals_bridge_dispatch_url = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_send_action = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_edit_action = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_draft_notification_action = serializers.CharField(
            required=False, allow_blank=True, default=""
        )
        telegram_approvals_bridge_token = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_message_template = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_header_new_template = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_header_step_approved_template = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_header_fully_approved_template = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_header_closed_template = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_header_rejected_template = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_subheader_payment_responsible_template = serializers.CharField(required=False, allow_blank=True, default="")
        telegram_approvals_subheader_rejected_by_template = serializers.CharField(required=False, allow_blank=True, default="")
        n8n_integration_token = serializers.CharField(required=False, allow_blank=True, default="")

    payment_types = serializers.ListField(child=RequestApprovalPaymentTypePayloadSerializer())
    integration_settings = IntegrationSettingsPayloadSerializer(required=False, default=dict)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)
        if not tenant:
            return attrs
        for pt_item in attrs.get("payment_types", []):
            payment_type = pt_item.get("payment_type")
            allowed_modes = set(
                payment_action_mode_choices_for_payment_type(
                    tenant=tenant,
                    payment_type=payment_type,
                )
            )
            for step_item in list(pt_item.get("steps") or []):
                if step_item.get("step_type") != Approval.STEP_TYPE_PAYMENT:
                    continue
                mode = step_item.get(
                    "payment_action_mode",
                    RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK,
                )
                if mode not in allowed_modes:
                    raise serializers.ValidationError(
                        {
                            "payment_types": (
                                f"Payment action mode '{mode}' is not available for "
                                f"payment_type '{payment_type}'."
                            )
                        }
                    )
        return attrs


class ApproverCandidateSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username"]

    def get_username(self, obj):
        return _display_user_name(obj)


def build_request_approval_config_response(*, tenant) -> dict:
    """
    Returns config + candidates for admin UI.
    """
    cfg = RequestApprovalConfig.objects.filter(tenant=tenant).first()

    active_member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
    approver_candidates_qs = User.objects.filter(id__in=active_member_ids).order_by("username")

    approver_candidates = ApproverCandidateSerializer(approver_candidates_qs, many=True).data

    payment_types_rows: list[dict] = []
    for pt_value, _ in Request.PAYMENT_TYPE_CHOICES:
        row = {"payment_type": pt_value, "is_enabled": False, "steps": []}
        row["payment_action_mode_options"] = payment_action_mode_choices_for_payment_type(
            tenant=tenant,
            payment_type=pt_value,
        )
        if cfg:
            pt_cfg = RequestApprovalPaymentTypeConfig.objects.filter(config=cfg, payment_type=pt_value).first()
            if pt_cfg:
                row["is_enabled"] = bool(pt_cfg.is_enabled)
                step_qs = pt_cfg.steps.order_by("step", "id").all()
                for step in step_qs:
                    row["steps"].append(
                        {
                            "step": step.step,
                            "step_type": step.step_type,
                            "is_enabled": bool(step.is_enabled),
                            "approver_user_ids": list(step.approvers.values_list("approver_user_id", flat=True)),
                            "payment_action_mode": step.payment_action_mode,
                            "payment_webapp_url": step.payment_webapp_url or "",
                        }
                    )
        payment_types_rows.append(row)

    integration_settings = {
        "telegram_approvals_bridge_dispatch_url": cfg.telegram_approvals_bridge_dispatch_url if cfg else "",
        "telegram_approvals_send_action": cfg.telegram_approvals_send_action if cfg else "",
        "telegram_approvals_edit_action": cfg.telegram_approvals_edit_action if cfg else "",
        "telegram_approvals_draft_notification_action": cfg.telegram_approvals_draft_notification_action if cfg else "",
        "telegram_approvals_bridge_token": cfg.telegram_approvals_bridge_token if cfg else "",
        "telegram_approvals_message_template": cfg.telegram_approvals_message_template if cfg else "",
        "telegram_approvals_header_new_template": cfg.telegram_approvals_header_new_template if cfg else "",
        "telegram_approvals_header_step_approved_template": cfg.telegram_approvals_header_step_approved_template if cfg else "",
        "telegram_approvals_header_fully_approved_template": cfg.telegram_approvals_header_fully_approved_template if cfg else "",
        "telegram_approvals_header_closed_template": cfg.telegram_approvals_header_closed_template if cfg else "",
        "telegram_approvals_header_rejected_template": cfg.telegram_approvals_header_rejected_template if cfg else "",
        "telegram_approvals_subheader_payment_responsible_template": cfg.telegram_approvals_subheader_payment_responsible_template if cfg else "",
        "telegram_approvals_subheader_rejected_by_template": cfg.telegram_approvals_subheader_rejected_by_template if cfg else "",
        "n8n_integration_token": cfg.n8n_integration_token if cfg else "",
    }
    return {
        "payment_types": payment_types_rows,
        "approver_candidates": approver_candidates,
        "integration_settings": integration_settings,
    }


def validate_auto_template_against_form_config(*, tenant, item: dict) -> None:
    """
    When tenant has request form config, auto-templates must follow the same rules as portal creates:
    enabled payment type, requester subset, vendor from allowed list / kind match, purpose from list when configured.
    """
    cfg = RequestFormConfig.objects.filter(tenant=tenant).first()
    if not cfg:
        return
    payment_type = item["payment_type"]
    pt_cfg = RequestFormPaymentTypeConfig.objects.filter(config=cfg, payment_type=payment_type).first()
    if not pt_cfg or not pt_cfg.is_enabled:
        raise serializers.ValidationError(
            f'Тип оплаты «{payment_type}» должен быть включён в настройках формы заявки (settings/request-form-config).'
        )
    requester_id = int(item["requester_id"])
    allowed_requester_ids = list(
        RequestFormPaymentTypeRequester.objects.filter(payment_type_config=pt_cfg).values_list(
            "user_id", flat=True
        )
    )
    if allowed_requester_ids and requester_id not in set(allowed_requester_ids):
        raise serializers.ValidationError("Выбранный заявитель не разрешён для этого типа оплаты в настройках формы.")

    vendor_ref_id = item.get("vendor_ref_id")
    if not vendor_ref_id:
        raise serializers.ValidationError("Выберите поставщика из справочника.")
    vendor = Vendor.objects.filter(tenant=tenant, id=int(vendor_ref_id)).first()
    if not vendor:
        raise serializers.ValidationError("Поставщик не найден.")
    if vendor.kind != payment_type_to_vendor_kind(payment_type):
        raise serializers.ValidationError("Вид поставщика не соответствует типу оплаты.")
    allowed_vendor_ids = list(
        RequestFormPaymentTypeVendor.objects.filter(payment_type_config=pt_cfg).values_list("vendor_id", flat=True)
    )
    if allowed_vendor_ids and vendor.id not in set(allowed_vendor_ids):
        raise serializers.ValidationError("Поставщик не разрешён для этого типа оплаты в настройках формы.")

    purpose_value = str(item.get("payment_purpose") or "").strip()
    purpose_rows = list(
        RequestPaymentPurposeConfig.objects.filter(payment_type_config=pt_cfg, is_active=True)
    )
    if purpose_rows:
        if not purpose_value:
            raise serializers.ValidationError("Выберите назначение платежа.")
        if not any(p.name == purpose_value for p in purpose_rows):
            raise serializers.ValidationError("Назначение платежа не входит в список для этого типа оплаты.")


class AutoRequestTemplatePayloadSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    is_enabled = serializers.BooleanField(required=False, default=False)
    name = serializers.CharField(required=False, allow_blank=True, max_length=150, default="")
    payment_type = serializers.ChoiceField(choices=Request.PAYMENT_TYPE_CHOICES)
    day_of_month = serializers.IntegerField(min_value=1, max_value=31)
    title_template = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    description_template = serializers.CharField(required=False, allow_blank=True, default="")
    amount = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=12,
        decimal_places=2,
        default=None,
    )
    currency = serializers.ChoiceField(
        choices=Request.CURRENCY_CHOICES, required=False, default=Request.CURRENCY_UZS
    )
    urgency = serializers.ChoiceField(
        choices=Request.URGENCY_CHOICES, required=False, default=Request.URGENCY_NORMAL
    )
    payment_purpose = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    vendor_ref_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    requester_id = serializers.IntegerField()
    billing_month_mode = serializers.ChoiceField(
        choices=AutoRequestTemplate.BILLING_MONTH_MODE_CHOICES,
        required=False,
        default=AutoRequestTemplate.BILLING_MONTH_CURRENT,
    )


class AutoRequestConfigPayloadSerializer(serializers.Serializer):
    templates = serializers.ListField(child=AutoRequestTemplatePayloadSerializer(), default=list)


def build_auto_request_config_response(*, tenant) -> dict:
    vendor_candidates = Vendor.objects.filter(tenant=tenant).order_by("name")
    templates = AutoRequestTemplate.objects.filter(tenant=tenant).order_by("id")
    form_cfg = build_request_form_config_response(tenant=tenant)
    return {
        "templates": [
            {
                "id": row.id,
                "is_enabled": bool(row.is_enabled),
                "name": row.name,
                "payment_type": row.payment_type,
                "day_of_month": row.day_of_month,
                "title_template": row.title_template,
                "description_template": row.description_template,
                "amount": str(row.amount) if row.amount is not None else None,
                "currency": row.currency,
                "urgency": row.urgency,
                "payment_purpose": row.payment_purpose,
                "vendor_ref_id": row.vendor_ref_id,
                "requester_id": row.requester_id,
                "billing_month_mode": row.billing_month_mode,
                "last_run_month": row.last_run_month.isoformat() if row.last_run_month else None,
            }
            for row in templates
        ],
        "vendor_candidates": VendorCandidateSerializer(vendor_candidates, many=True).data,
        "form_payment_types": form_cfg["payment_types"],
        "requester_candidates": form_cfg["requester_candidates"],
    }

