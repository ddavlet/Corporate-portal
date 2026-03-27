from rest_framework import serializers

from apps.modules.bank_expenses.models import BankExpense, BankRevenue


class BankExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankExpense
        fields = [
            "id",
            "created_at",
            "created_by",
            "row_no",
            "doc_date",
            "process_date",
            "doc_no",
            "account_name",
            "inn",
            "account_no",
            "mfo",
            "debit_turnover",
            "payment_purpose",
        ]
        read_only_fields = ["id", "created_at", "created_by"]


class BankRevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankRevenue
        fields = [
            "id",
            "created_at",
            "created_by",
            "row_no",
            "doc_date",
            "process_date",
            "doc_no",
            "account_name",
            "inn",
            "account_no",
            "mfo",
            "kredit_turnover",
            "payment_purpose",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

