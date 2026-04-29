from rest_framework import serializers

from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentReturnApproval,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
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


class InvestReturnSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = InvestReturn
        fields = [
            "id",
            "tenant",
            "company",
            "date",
            "sum",
            "sum_uzs",
            "comment",
            "confirmed",
            "currency",
            "type",
            "recipient",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        return attrs


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
        return attrs


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
        return attrs


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
        return attrs


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
    is_enabled = serializers.BooleanField(default=True)
    approver_user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )


class InvestmentApprovalConfigSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(default=False)
    steps = InvestmentApprovalConfigStepSerializer(many=True)
    approver_candidates = serializers.ListField(read_only=True)

    def validate_steps(self, value):
        seen_steps: set[int] = set()
        for row in value:
            step = int(row["step"])
            if step in seen_steps:
                raise serializers.ValidationError("Step numbers must be unique.")
            seen_steps.add(step)
            if row.get("is_enabled", True) and not row.get("approver_user_ids"):
                raise serializers.ValidationError("Enabled step must contain at least one approver.")
        return value


class InvestmentApprovalDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[InvestmentReturnApproval.DECISION_APPROVED, InvestmentReturnApproval.DECISION_REJECTED]
    )
    approver_tg_id = serializers.IntegerField(required=False)
    approver_tg_from_id = serializers.IntegerField(required=False)
    comment = serializers.CharField(required=False, allow_blank=True)


class InvestmentApprovalWebhookSerializer(serializers.Serializer):
    update = serializers.JSONField(required=False)
    callback_query = serializers.JSONField(required=False)

    def validate(self, attrs):
        if attrs.get("update") or attrs.get("callback_query"):
            return attrs
        raise serializers.ValidationError({"detail": "Payload must contain update or callback_query."})
