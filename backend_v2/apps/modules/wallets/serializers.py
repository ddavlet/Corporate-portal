from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.modules.wallets.models import CashRegister, Wallet


class CashRegisterSerializer(serializers.ModelSerializer):
    wallet_id = serializers.IntegerField(source="wallet.id", read_only=True)

    class Meta:
        model = CashRegister
        fields = [
            "id",
            "tenant",
            "currency",
            "name",
            "code",
            "description",
            "is_active",
            "sort_order",
            "is_default_for_currency",
            "wallet_id",
        ]
        read_only_fields = ["id", "tenant", "wallet_id"]

    def create(self, validated_data):
        tenant = validated_data["tenant"]
        try:
            with transaction.atomic():
                reg = CashRegister.objects.create(**validated_data)
                Wallet.objects.create(
                    tenant=tenant,
                    wallet_type=Wallet.Type.CASH,
                    currency=reg.currency,
                    cash_register=reg,
                    opening_balance=0,
                )
                return reg
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"currency": "Касса с этой валютой уже существует."}
            ) from exc


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = [
            "id",
            "tenant",
            "wallet_type",
            "currency",
            "opening_balance",
            "opening_balance_at",
            "cash_register_id",
            "bank_account_id",
            "corporate_card_account_id",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "wallet_type",
            "currency",
            "cash_register_id",
            "bank_account_id",
            "corporate_card_account_id",
        ]

    def update(self, instance, validated_data):
        allowed = {"opening_balance", "opening_balance_at"}
        extra = set(validated_data.keys()) - allowed
        if extra:
            raise serializers.ValidationError({k: "Read-only field." for k in extra})
        return super().update(instance, validated_data)
