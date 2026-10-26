from rest_framework import serializers

from apps.modules.kapitalbank.models import BankAccountLink


class PendingAccountSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(
        source="last_balance", max_digits=18, decimal_places=2, coerce_to_string=True, allow_null=True
    )

    class Meta:
        model = BankAccountLink
        fields = ["account_no", "branch", "name", "currency", "balance", "first_seen_at"]
        read_only_fields = fields
