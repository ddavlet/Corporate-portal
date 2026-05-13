from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers

from apps.modules.investments.billing_month_rules import (
    is_accrual_month_allowed,
    month_first_day,
)
from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentFormConfig,
    InvestmentReturnApproval,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
)
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
        read_only_fields = ["id", "tenant", "cbu_usd_uzs_rate", "created_at", "last_edit_at", "created_by"]

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

        skip_bd_window = bool(self.context.get("skip_invest_return_billing_window"))
        merged_date = attrs.get("date")
        if merged_date is None and self.instance is not None:
            merged_date = self.instance.date

        billing_in_attrs = "billing_date" in attrs
        billing_explicit = attrs.get("billing_date") if billing_in_attrs else None

        if self.instance is None:
            if merged_date is None:
                raise serializers.ValidationError({"date": "Укажите дату выплаты."})
            billing_source = billing_explicit if billing_explicit is not None else merged_date
            bd = month_first_day(billing_source)
            if not skip_bd_window and not is_accrual_month_allowed(bd):
                raise serializers.ValidationError(
                    {
                        "billing_date": "Месяц назначения недоступен. Выберите один из допустимых месяцев "
                        "(как при создании заявки на расход ДС)."
                    }
                )
            attrs["billing_date"] = bd
        elif billing_in_attrs:
            if billing_explicit is None:
                raise serializers.ValidationError({"billing_date": "Укажите месяц назначения."})
            bd = month_first_day(billing_explicit)
            if not skip_bd_window and not is_accrual_month_allowed(bd):
                raise serializers.ValidationError(
                    {
                        "billing_date": "Месяц назначения недоступен. Выберите один из допустимых месяцев "
                        "(как при создании заявки на расход ДС)."
                    }
                )
            attrs["billing_date"] = bd

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
            "payment_amount",
            "comment",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
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
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

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
    payment_chat_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    approver_user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
    )


class InvestmentFormConfigSerializer(serializers.Serializer):
    uses_companies = serializers.BooleanField()
    allowed_return_types = serializers.ListField(
        child=serializers.ChoiceField(choices=InvestReturn.ReturnType.choices),
        allow_empty=False,
    )


class InvestmentApprovalConfigSerializer(serializers.Serializer):
    return_type = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=25)
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

    def validate_steps(self, value):
        seen_steps: set[int] = set()
        for row in value:
            step = int(row["step"])
            if step in seen_steps:
                raise serializers.ValidationError("Step numbers must be unique.")
            seen_steps.add(step)
            step_type = row.get("step_type") or InvestmentApprovalConfigStep.STEP_TYPE_SERIAL
            is_enabled = row.get("is_enabled", True)
            approver_ids = row.get("approver_user_ids") or []
            if is_enabled:
                if step_type != InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION and not approver_ids:
                    raise serializers.ValidationError("У активного этапа должен быть хотя бы один согласующий.")
                if step_type in (
                    InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION,
                ):
                    if row.get("payment_chat_id") in (None, ""):
                        raise serializers.ValidationError(
                            "Для этапов confirmation и notification нужен payment_chat_id (Telegram chat)."
                        )
            if step_type == InvestmentApprovalConfigStep.STEP_TYPE_SERIAL:
                row["payment_chat_id"] = None
        return value


class InvestmentApprovalDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[InvestmentReturnApproval.DECISION_APPROVED, InvestmentReturnApproval.DECISION_REJECTED]
    )
    approver_recipient_id = serializers.IntegerField(required=False)
    approver_external_user_id = serializers.IntegerField(required=False)
    comment = serializers.CharField(required=False, allow_blank=True)


class InvestmentApprovalWebhookSerializer(serializers.Serializer):
    event = serializers.CharField()
    payload = serializers.CharField()
    user_id = serializers.CharField()
    recipient_id = serializers.CharField()
    message_id = serializers.IntegerField(required=False)
    platform = serializers.CharField(default="telegram")
