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


class UntrackedAccountSerializer(serializers.ModelSerializer):
    """Accounts the portal does not track: awaiting a decision ("pending") or marked service ("service")."""

    balance = serializers.DecimalField(
        source="last_balance", max_digits=18, decimal_places=2, coerce_to_string=True, allow_null=True
    )
    status = serializers.SerializerMethodField()
    reason = serializers.CharField(source="ignore_reason", read_only=True)

    class Meta:
        model = BankAccountLink
        fields = ["account_no", "branch", "name", "currency", "balance", "status", "reason"]
        read_only_fields = fields

    def get_status(self, obj) -> str:
        return "service" if obj.decision == BankAccountLink.IGNORED else "pending"
