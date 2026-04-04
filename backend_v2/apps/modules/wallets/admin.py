from django.contrib import admin

from apps.modules.wallets.models import BankAccount, CashRegister, CorporateCardAccount, Wallet


@admin.register(CashRegister)
class CashRegisterAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "currency", "name", "is_active")
    list_filter = ("is_active",)


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "label")


@admin.register(CorporateCardAccount)
class CorporateCardAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "currency", "label")


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "wallet_type", "currency", "opening_balance")
