from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.modules.wallets.models import BankAccount, CashRegister, CorporateCardAccount, Wallet


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
                if (
                    validated_data.get("is_default_for_currency")
                    and validated_data.get("currency")
                ):
                    CashRegister.objects.filter(
                        tenant=tenant,
                        currency=validated_data["currency"],
                        is_default_for_currency=True,
                    ).update(is_default_for_currency=False)
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
            raise serializers.ValidationError({"detail": "Не удалось создать кассу."}) from exc


class BankAccountSerializer(serializers.ModelSerializer):
    """
    Синтетический якорь выписки: поля account_no/mfo здесь — справочные/плейсхолдеры,
    не реквизиты контрагента из строк BankExpense/BankRevenue.
    """

    wallet_id = serializers.IntegerField(source="wallet.id", read_only=True)

    class Meta:
        model = BankAccount
        fields = ["id", "tenant", "label", "account_no", "mfo", "wallet_id"]
        read_only_fields = ["id", "tenant", "wallet_id"]

    def create(self, validated_data):
        tenant = validated_data["tenant"]
        validated_data.setdefault("label", "Основной")
        validated_data.setdefault("account_no", "")
        validated_data.setdefault("mfo", "")
        try:
            with transaction.atomic():
                ba = BankAccount.objects.create(**validated_data)
                Wallet.objects.create(
                    tenant=tenant,
                    wallet_type=Wallet.Type.BANK,
                    currency="UZS",
                    bank_account=ba,
                    opening_balance=0,
                )
                return ba
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"detail": "Банковский счёт для этого тенанта уже существует (один на компанию)."}
            ) from exc


class CorporateCardAccountSerializer(serializers.ModelSerializer):
    wallet_id = serializers.IntegerField(source="wallet.id", read_only=True)

    class Meta:
        model = CorporateCardAccount
        fields = ["id", "tenant", "currency", "label", "external_ref", "wallet_id"]
        read_only_fields = ["id", "tenant", "wallet_id"]

    def create(self, validated_data):
        tenant = validated_data["tenant"]
        cur = validated_data["currency"]
        try:
            with transaction.atomic():
                acc = CorporateCardAccount.objects.create(**validated_data)
                Wallet.objects.create(
                    tenant=tenant,
                    wallet_type=Wallet.Type.CORPORATE_CARD,
                    currency=cur,
                    corporate_card_account=acc,
                    opening_balance=0,
                )
                return acc
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"currency": "Счёт корпкарты в этой валюте уже существует."}
            ) from exc

    def update(self, instance, validated_data):
        validated_data.pop("currency", None)
        return super().update(instance, validated_data)


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
