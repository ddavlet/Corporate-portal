"""
Wallets and per-channel anchors.

BankAccount v1 is a synthetic tenant-level anchor: `account_no` / `mfo` here are NOT copied from
statement lines — those fields describe the counterparty on each BankExpense/BankRevenue row, not "our" account.
"""

from django.db import models

from apps.tenants.models import Tenant


class CashRegister(models.Model):
    """One row per (tenant, currency) in v1."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cash_registers")
    currency = models.CharField(max_length=10)
    name = models.CharField(max_length=255, blank=True, default="")
    code = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    is_default_for_currency = models.BooleanField(default=False)

    class Meta:
        db_table = "wallets_cash_registers"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "currency"], name="wallets_cashreg_tenant_currency_uniq"),
        ]


class BankAccount(models.Model):
    """
    v1: exactly one synthetic row per tenant for the single bank Wallet.
    Do not treat statement `account_no` as this anchor — see module docstring.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bank_accounts_wallets")
    label = models.CharField(max_length=255, default="Основной")
    account_no = models.CharField(max_length=34, blank=True, default="")
    mfo = models.CharField(max_length=10, blank=True, default="")

    class Meta:
        db_table = "wallets_bank_accounts"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="wallets_bankaccount_one_per_tenant"),
        ]


class CorporateCardAccount(models.Model):
    """One row per (tenant, currency) in v1."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="corporate_card_accounts")
    currency = models.CharField(max_length=10)
    label = models.CharField(max_length=255, blank=True, default="")
    external_ref = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "wallets_corporate_card_accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "currency"],
                name="wallets_corpacct_tenant_currency_uniq",
            ),
        ]


class Wallet(models.Model):
    class Type(models.TextChoices):
        CASH = "cash", "Cash"
        BANK = "bank", "Bank"
        CORPORATE_CARD = "corporate_card", "Corporate card"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="wallets")
    wallet_type = models.CharField(max_length=20, choices=Type.choices)
    currency = models.CharField(max_length=10)
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    opening_balance_at = models.DateTimeField(null=True, blank=True)

    cash_register = models.OneToOneField(
        CashRegister,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wallet",
    )
    bank_account = models.OneToOneField(
        BankAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wallet",
    )
    corporate_card_account = models.OneToOneField(
        CorporateCardAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wallet",
    )

    class Meta:
        db_table = "wallets_wallets"
        indexes = [
            models.Index(fields=["tenant", "wallet_type"], name="wallets_wallet_tenant_type_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        wallet_type="cash",
                        cash_register__isnull=False,
                        bank_account__isnull=True,
                        corporate_card_account__isnull=True,
                    )
                    | models.Q(
                        wallet_type="bank",
                        bank_account__isnull=False,
                        cash_register__isnull=True,
                        corporate_card_account__isnull=True,
                    )
                    | models.Q(
                        wallet_type="corporate_card",
                        corporate_card_account__isnull=False,
                        cash_register__isnull=True,
                        bank_account__isnull=True,
                    )
                ),
                name="wallets_wallet_type_fk_alignment",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.wallet_type == self.Type.CASH:
            if not self.cash_register_id or self.bank_account_id or self.corporate_card_account_id:
                raise ValidationError("Cash wallet requires cash_register only.")
            if self.cash_register and self.cash_register.currency != self.currency:
                raise ValidationError("Wallet currency must match cash register currency.")
        elif self.wallet_type == self.Type.BANK:
            if not self.bank_account_id or self.cash_register_id or self.corporate_card_account_id:
                raise ValidationError("Bank wallet requires bank_account only.")
        elif self.wallet_type == self.Type.CORPORATE_CARD:
            if not self.corporate_card_account_id or self.cash_register_id or self.bank_account_id:
                raise ValidationError("Corporate card wallet requires corporate_card_account only.")
            if self.corporate_card_account and self.corporate_card_account.currency != self.currency:
                raise ValidationError("Wallet currency must match corporate card account currency.")

