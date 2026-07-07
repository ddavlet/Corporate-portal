from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers

from apps.modules.investments.billing_month_rules import month_first_day
from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentFormConfig,
    InvestmentProjectApprovalConfig,
    InvestmentProjectApprovalConfigStep,
    InvestmentProjectApprovalConfigStepApprover,
    InvestmentReturnApproval,
    InvestNotificationConfig,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.requests.serializers import _display_user_name
from apps.modules.investments.services import (
    CbuRateFetchError,
    clamp_rate_date_to_cbu_availability,
    fetch_cbu_usd_uzs_rate,
    tashkent_today,
)
from apps.modules.serializers_guard import reject_client_pk_on_create


def _normalize_currency(attrs: dict, key: str = "currency") -> None:
    val = attrs.get(key)
    if val is not None:
        attrs[key] = str(val).strip().upper()


class _CompanyScopeMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company_field = self.fields.get("company")
        if company_field is None:
            return
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            company_field.queryset = InvestCompany.objects.filter(tenant=tenant)
        else:
            company_field.queryset = InvestCompany.objects.none()


def investment_form_clear_company_if_disabled(attrs, request) -> dict:
    """When tenant disabled companies in form settings, drop company FK on write."""
    tenant = getattr(request, "tenant", None)
    if not tenant:
        return attrs
    cfg = InvestmentFormConfig.objects.filter(tenant=tenant).first()
    if cfg and not cfg.uses_companies:
        attrs["company"] = None
    return attrs


class InvestReturnSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = InvestReturn
        fields = [
            "id",
            "tenant",
            "company",
            "payout_schedule",
            "date",
            "billing_date",
            "sum",
            "sum_uzs",
            "cbu_usd_uzs_rate",
            "comment",
            "confirmed",
            "currency",
            "type",
            "recipient",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "payout_schedule",
            "cbu_usd_uzs_rate",
            "created_at",
            "last_edit_at",
            "created_by",
        ]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        attrs.pop("sum_uzs", None)
        merged_currency = attrs.get("currency")
        if self.instance is not None:
            merged_currency = merged_currency or self.instance.currency
        else:
            merged_currency = merged_currency or "USD"
        merged_currency = str(merged_currency or "USD").strip().upper()
        if merged_currency not in ("USD", "UZS"):
            raise serializers.ValidationError({"currency": "Допустимы только USD и UZS."})

        merged_date = attrs.get("date")
        if merged_date is None and self.instance is not None:
            merged_date = self.instance.date

        billing_in_attrs = "billing_date" in attrs
        billing_explicit = attrs.get("billing_date") if billing_in_attrs else None

        if self.instance is None:
            if merged_date is None:
                raise serializers.ValidationError({"date": "Укажите дату выплаты."})
            billing_source = billing_explicit if billing_explicit is not None else merged_date
            attrs["billing_date"] = month_first_day(billing_source)
        elif billing_in_attrs:
            if billing_explicit is None:
                raise serializers.ValidationError({"billing_date": "Укажите месяц назначения."})
            attrs["billing_date"] = month_first_day(billing_explicit)

        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            cfg = InvestmentFormConfig.objects.filter(tenant=tenant).first()
            if cfg:
                allowed = cfg.allowed_return_types or []
                if allowed:
                    merged_type = attrs.get("type")
                    if merged_type is None and self.instance is not None:
                        merged_type = self.instance.type
                    if merged_type not in allowed:
                        raise serializers.ValidationError(
                            {"type": "Этот тип выплат отключён в настройках формы инвестиций."}
                        )
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))

    def create(self, validated_data):
        try:
            rate = fetch_cbu_usd_uzs_rate(rate_date=tashkent_today())
        except CbuRateFetchError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        currency = str(validated_data["currency"]).strip().upper()
        d_sum = Decimal(str(validated_data["sum"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if currency == "UZS":
            validated_data["sum"] = d_sum
            validated_data["sum_uzs"] = d_sum
        else:
            validated_data["sum"] = d_sum
            validated_data["sum_uzs"] = (d_sum * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        validated_data["cbu_usd_uzs_rate"] = rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "sum" in validated_data or "currency" in validated_data:
            rate = instance.cbu_usd_uzs_rate
            if rate is None:
                try:
                    rate = fetch_cbu_usd_uzs_rate(
                        rate_date=clamp_rate_date_to_cbu_availability(requested=instance.date)
                    )
                except CbuRateFetchError as exc:
                    raise serializers.ValidationError({"detail": str(exc)}) from exc
            currency = str(validated_data.get("currency", instance.currency)).strip().upper()
            base_sum = validated_data.get("sum", instance.sum)
            d_sum = Decimal(str(base_sum)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if currency == "UZS":
                validated_data["sum"] = d_sum
                validated_data["sum_uzs"] = d_sum
            else:
                validated_data["sum"] = d_sum
                validated_data["sum_uzs"] = (d_sum * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if instance.cbu_usd_uzs_rate is None:
                validated_data["cbu_usd_uzs_rate"] = rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        return super().update(instance, validated_data)


class InvestPayoutScheduleSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    remaining_amount = serializers.SerializerMethodField()

    class Meta:
        model = InvestPayoutSchedule
        fields = [
            "id",
            "tenant",
            "company",
            "payout_date",
            "amount",
            "currency",
            "is_paid",
            "closed_manually",
            "payment_amount",
            "remaining_amount",
            "comment",
            "return_type",
            "recipient",
            "created_return",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "closed_manually",
            "created_return",
            "created_at",
            "last_edit_at",
            "created_by",
        ]

    def get_remaining_amount(self, obj) -> str:
        """Outstanding amount still owed (amount - already-paid), clamped at zero."""
        remaining = Decimal(str(obj.amount or 0)) - Decimal(str(obj.payment_amount or 0))
        if remaining < 0:
            remaining = Decimal("0")
        return str(remaining.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        # Editing is_paid directly (admin form) is treated as a manual open/close decision so
        # the soft-coupling recompute respects it: closing keeps the schedule closed even when
        # under-paid; reopening lets the amount-based auto-status take over again.
        if "is_paid" in attrs:
            attrs["closed_manually"] = bool(attrs["is_paid"])
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))


class ProjectInvestmentSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = ProjectInvestment
        fields = [
            "id",
            "tenant",
            "company",
            "date",
            "amount",
            "currency",
            "comment",
            "confirmed",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "confirmed", "created_at", "last_edit_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))


class InvestCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestCompany
        fields = [
            "id",
            "tenant",
            "name",
            "comment",
            "is_active",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

    def validate_name(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise serializers.ValidationError("Name cannot be empty.")
        return normalized

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        return attrs


class InvestPayoutScheduleShareLinkSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = InvestPayoutScheduleShareLink
        fields = [
            "id",
            "tenant",
            "token",
            "company",
            "paid_filter",
            "is_active",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "token", "is_active", "created_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))


class PublicInvestPayoutScheduleShareViewSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    payout_date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    is_paid = serializers.BooleanField()
    payment_amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    comment = serializers.CharField(allow_blank=True)
    company = serializers.IntegerField(allow_null=True)
    company_name = serializers.CharField(allow_blank=True)
    currency = serializers.CharField()


class InvestmentApprovalConfigStepSerializer(serializers.Serializer):
    step = serializers.IntegerField(min_value=1)
    step_type = serializers.ChoiceField(
        choices=InvestmentApprovalConfigStep.STEP_TYPE_CHOICES,
        default=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
    )
    is_enabled = serializers.BooleanField(default=True)
    telegram_chat_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    approver_user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
    )


class InvestNotificationConfigSerializer(serializers.Serializer):
    responsible_user_id = serializers.IntegerField(min_value=1)
    days_before = serializers.IntegerField(min_value=1, max_value=365)
    overdue_notify_every_days = serializers.IntegerField(min_value=0, max_value=365)
    notify_hour = serializers.IntegerField(min_value=0, max_value=23)
    is_active = serializers.BooleanField()
    telegram_chat_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class InvestmentFormConfigSerializer(serializers.Serializer):
    uses_companies = serializers.BooleanField()
    allowed_return_types = serializers.ListField(
        child=serializers.ChoiceField(choices=InvestReturn.ReturnType.choices),
        allow_empty=False,
    )


class InvestmentApprovalConfigSerializer(serializers.Serializer):
    return_type = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=25)
    recipient = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=20)
    is_enabled = serializers.BooleanField(default=False)
    steps = InvestmentApprovalConfigStepSerializer(many=True)
    approver_candidates = serializers.ListField(read_only=True)

    def validate_return_type(self, value):
        if value in (None, ""):
            return None
        valid = {c[0] for c in InvestReturn.ReturnType.choices}
        if value not in valid:
            raise serializers.ValidationError("Недопустимый тип выплаты.")
        return value

    def validate_recipient(self, value):
        if value in (None, ""):
            return None
        valid = {c[0] for c in InvestReturn.Recipient.choices}
        if value not in valid:
            raise serializers.ValidationError("Недопустимый получатель.")
        return value

    def validate_steps(self, value):
        raw_steps = (getattr(self, "initial_data", None) or {}).get("steps")
        raw_by_step: dict[int, dict] = {}
        if isinstance(raw_steps, list):
            for r in raw_steps:
                if isinstance(r, dict) and "step" in r:
                    try:
                        raw_by_step[int(r["step"])] = r
                    except (TypeError, ValueError):
                        continue
        seen_steps: set[int] = set()
        for row in value:
            step = int(row["step"])
            if step in seen_steps:
                raise serializers.ValidationError("Step numbers must be unique.")
            seen_steps.add(step)
            raw = raw_by_step.get(step, {})
            # После вложенного сериализатора step_type иногда не попадает в row — берём из initial_data.
            step_type = (
                row.get("step_type")
                or raw.get("step_type")
                or InvestmentApprovalConfigStep.STEP_TYPE_SERIAL
            )
            is_enabled = row.get("is_enabled", True)
            approver_ids = row.get("approver_user_ids") or raw.get("approver_user_ids") or []
            if is_enabled:
                if step_type != InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION and not approver_ids:
                    raise serializers.ValidationError("У активного этапа должен быть хотя бы один согласующий.")
                if step_type in (
                    InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION,
                ):
                    chat_id = row.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        chat_id = raw.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        raise serializers.ValidationError(
                            "Для этапов confirmation и notification нужен telegram_chat_id (Telegram чат)."
                        )
                    row["telegram_chat_id"] = chat_id
            row["step_type"] = step_type
            if step_type == InvestmentApprovalConfigStep.STEP_TYPE_SERIAL:
                row["telegram_chat_id"] = None
        return value


class InvestmentApprovalDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[InvestmentReturnApproval.DECISION_APPROVED, InvestmentReturnApproval.DECISION_REJECTED]
    )
    approver_recipient_id = serializers.IntegerField(required=False)
    approver_external_user_id = serializers.IntegerField(required=False)
    comment = serializers.CharField(required=False, allow_blank=True)


class InvestmentProjectApprovalConfigSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(default=False)
    steps = InvestmentApprovalConfigStepSerializer(many=True)

    def validate_steps(self, value):
        raw_steps = (getattr(self, "initial_data", None) or {}).get("steps")
        raw_by_step: dict[int, dict] = {}
        if isinstance(raw_steps, list):
            for r in raw_steps:
                if isinstance(r, dict) and "step" in r:
                    try:
                        raw_by_step[int(r["step"])] = r
                    except (TypeError, ValueError):
                        continue
        seen_steps: set[int] = set()
        for row in value:
            step = int(row["step"])
            if step in seen_steps:
                raise serializers.ValidationError("Step numbers must be unique.")
            seen_steps.add(step)
            raw = raw_by_step.get(step, {})
            step_type = (
                row.get("step_type")
                or raw.get("step_type")
                or InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL
            )
            is_enabled = row.get("is_enabled", True)
            approver_ids = row.get("approver_user_ids") or raw.get("approver_user_ids") or []
            if is_enabled:
                if step_type != InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION and not approver_ids:
                    raise serializers.ValidationError("У активного этапа должен быть хотя бы один согласующий.")
                if step_type in (
                    InvestmentProjectApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION,
                ):
                    chat_id = row.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        chat_id = raw.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        raise serializers.ValidationError(
                            "Для этапов confirmation и notification нужен telegram_chat_id (Telegram чат)."
                        )
                    row["telegram_chat_id"] = chat_id
            row["step_type"] = step_type
            if step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL:
                row["telegram_chat_id"] = None
        return value


class InvestmentApprovalWebhookSerializer(serializers.Serializer):
    event = serializers.CharField()
    payload = serializers.CharField()
    user_id = serializers.CharField()
    recipient_id = serializers.CharField()
    message_id = serializers.IntegerField(required=False)
    platform = serializers.CharField(default="telegram")


# --- Read-only serializers for admin / module data inspection (list + retrieve only) ---


class InvestmentFormConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentFormConfig
        fields = ["id", "tenant", "uses_companies", "allowed_return_types", "created_at", "updated_at"]
        read_only_fields = fields


class InvestmentApprovalConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentApprovalConfig
        fields = ["id", "tenant", "return_type", "recipient", "is_enabled", "created_at", "updated_at"]
        read_only_fields = fields


class InvestmentApprovalConfigStepReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentApprovalConfigStep
        fields = ["id", "config", "step", "step_type", "is_enabled", "telegram_chat_id"]
        read_only_fields = fields


class InvestmentApprovalConfigStepApproverReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentApprovalConfigStepApprover
        fields = ["id", "step", "approver_user"]
        read_only_fields = fields


class InvestmentReturnApprovalReadSerializer(serializers.ModelSerializer):
    approver_username = serializers.SerializerMethodField()
    # Derived from the single source of truth (`telegram_message`); kept for API stability.
    gateway_message_id = serializers.ReadOnlyField()
    message_sent = serializers.ReadOnlyField()
    message_sent_at = serializers.ReadOnlyField()

    class Meta:
        model = InvestmentReturnApproval
        fields = [
            "id",
            "tenant",
            "invest_return",
            "step",
            "step_type",
            "approver_user",
            "approver_username",
            "approver_recipient_id",
            "approver_external_user_id",
            "decision",
            "decision_comment",
            "decided_at",
            "gateway_message_id",
            "message_sent",
            "message_sent_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_approver_username(self, obj):
        return _display_user_name(getattr(obj, "approver_user", None))


class InvestmentProjectApprovalConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentProjectApprovalConfig
        fields = ["id", "tenant", "is_enabled", "created_at", "updated_at"]
        read_only_fields = fields


class InvestmentProjectApprovalConfigStepReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentProjectApprovalConfigStep
        fields = ["id", "config", "step", "step_type", "is_enabled", "payment_chat_id"]
        read_only_fields = fields


class InvestmentProjectApprovalConfigStepApproverReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentProjectApprovalConfigStepApprover
        fields = ["id", "step", "approver_user"]
        read_only_fields = fields


class ProjectInvestmentApprovalReadSerializer(serializers.ModelSerializer):
    approver_username = serializers.SerializerMethodField()
    # Derived from the single source of truth (`telegram_message`); kept for API stability.
    gateway_message_id = serializers.ReadOnlyField()
    message_sent = serializers.ReadOnlyField()
    message_sent_at = serializers.ReadOnlyField()

    class Meta:
        model = ProjectInvestmentApproval
        fields = [
            "id",
            "tenant",
            "project_investment",
            "step",
            "step_type",
            "approver_user",
            "approver_username",
            "approver_recipient_id",
            "approver_external_user_id",
            "decision",
            "decision_comment",
            "decided_at",
            "gateway_message_id",
            "message_sent",
            "message_sent_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_approver_username(self, obj):
        return _display_user_name(getattr(obj, "approver_user", None))
