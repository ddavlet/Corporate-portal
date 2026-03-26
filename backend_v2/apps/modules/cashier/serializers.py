from rest_framework import serializers

from apps.modules.cashier.models import CashExpense, CashRevenue


class CashExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashExpense
        fields = [
            "id",
            "title",
            "amount",
            "currency",
            "expense_date",
            "category",
            "note",
            "payload",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class CashRevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashRevenue
        fields = [
            "id",
            "title",
            "amount",
            "currency",
            "revenue_date",
            "category",
            "received_from",
            "payment_method",
            "reference_no",
            "status",
            "tags",
            "note",
            "payload",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

