from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine
from apps.modules.payroll.payouts import document_label
from apps.modules.payroll.services import current_request_for_document


class PayrollLineSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = PayrollLine
        fields = [
            "id",
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
        read_only_fields = fields


class PayrollDocumentListSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    total_sum = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True, default=Decimal("0"))
    lines_count = serializers.IntegerField(read_only=True, default=0)
    has_request = serializers.BooleanField(read_only=True)
    has_paid_request = serializers.BooleanField(read_only=True)
    matched_request_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = PayrollDocument
        fields = [
            "id",
            "doc_id",
            "created_at",
            "total_sum",
            "lines_count",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]
        read_only_fields = fields


class PayrollDocumentDetailSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    lines = PayrollLineSerializer(many=True, read_only=True)
    total_sum = serializers.SerializerMethodField()

    class Meta:
        model = PayrollDocument
        fields = ["id", "doc_id", "created_at", "total_sum", "lines"]
        read_only_fields = fields

    def get_total_sum(self, obj):
        agg = obj.lines.aggregate(s=Sum("sum"))
        val = agg.get("s")
        return val if val is not None else Decimal("0")


class PayrollLineCreateSerializer(serializers.Serializer):
    employee = serializers.CharField()
    item = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")
    sum = serializers.DecimalField(max_digits=15, decimal_places=2)
    days_plan = serializers.IntegerField(required=False, allow_null=True, default=None)
    days_fact = serializers.IntegerField(required=False, allow_null=True, default=None)
    period_start = serializers.DateField(required=False, allow_null=True, default=None)
    period_end = serializers.DateField(required=False, allow_null=True, default=None)


class PayrollDocumentCreateSerializer(serializers.Serializer):
    lines = PayrollLineCreateSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Нужна хотя бы одна строка начисления.")
        return value


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "full_name"]
        read_only_fields = ["id"]


class EmployeeCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите ФИО.")
        return value


class PayrollDraftLineSerializer(serializers.Serializer):
    employee_id = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.none(), source="employee")
    sum = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0.01"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant is not None:
            self.fields["employee_id"].queryset = Employee.objects.filter(tenant=tenant)


class PayrollDraftSerializer(serializers.Serializer):
    period_month = serializers.DateField()
    kind = serializers.ChoiceField(choices=PayrollDocument.KIND_CHOICES)
    lines = PayrollDraftLineSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Нужна хотя бы одна строка начисления.")
        ids = [line["employee"].id for line in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Сотрудник указан в начислении дважды.")
        return value


class PayrollPayoutItemSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)


class PayrollPayoutCreateSerializer(serializers.Serializer):
    wallet_id = serializers.IntegerField()
    date = serializers.DateField()
    items = PayrollPayoutItemSerializer(many=True)


class PayrollCloseUnderpaidSerializer(serializers.Serializer):
    comment = serializers.CharField(allow_blank=True)


class PayrollLineDetailSerializer(PayrollLineSerializer):
    employee_id = serializers.IntegerField(source="employee_fk_id", read_only=True, allow_null=True)

    class Meta(PayrollLineSerializer.Meta):
        fields = PayrollLineSerializer.Meta.fields + ["employee_id"]
        read_only_fields = fields


class PayrollDocumentWorkflowListSerializer(PayrollDocumentListSerializer):
    label = serializers.SerializerMethodField()
    paid_total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True, default=Decimal("0"))

    class Meta(PayrollDocumentListSerializer.Meta):
        fields = PayrollDocumentListSerializer.Meta.fields + [
            "label", "status", "source", "payout_mode", "period_month", "kind", "paid_total",
        ]
        read_only_fields = fields

    def get_label(self, obj):
        return document_label(obj)


class PayrollDocumentWorkflowDetailSerializer(PayrollDocumentDetailSerializer):
    lines = PayrollLineDetailSerializer(many=True, read_only=True)
    label = serializers.SerializerMethodField()
    current_request = serializers.SerializerMethodField()
    paid_total = serializers.SerializerMethodField()
    remaining_total = serializers.SerializerMethodField()

    class Meta(PayrollDocumentDetailSerializer.Meta):
        fields = PayrollDocumentDetailSerializer.Meta.fields + [
            "label", "status", "source", "payout_mode", "period_month", "kind",
            "closed_underpaid_at", "close_comment", "current_request", "paid_total", "remaining_total",
        ]
        read_only_fields = fields

    def get_label(self, obj):
        return document_label(obj)

    def get_current_request(self, obj):
        req = current_request_for_document(obj)
        return {"id": req.id, "status": req.status} if req else None

    def _paid(self, obj):
        return obj.payouts.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    def get_paid_total(self, obj):
        return str(self._paid(obj))

    def get_remaining_total(self, obj):
        return str(max(self.get_total_sum(obj) - self._paid(obj), Decimal("0")))
