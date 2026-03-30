from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from apps.modules.payroll.models import PayrollDocument, PayrollLine
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
