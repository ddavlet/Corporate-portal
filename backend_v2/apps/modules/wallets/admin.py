from apps.common.admin_labels import register_portal
from django.contrib import admin

from apps.modules.wallets.models import BankAccount, CashRegister, CorporateCardAccount, Wallet


class CashRegisterAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "currency", "code", "is_active", "is_default_for_currency")
    list_filter = ("tenant", "currency", "is_active")
    search_fields = ("name", "code")
    autocomplete_fields = ("tenant",)


class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "label", "account_no", "mfo", "is_default")
    list_filter = ("tenant", "is_default")
    search_fields = ("label", "account_no", "mfo")
    autocomplete_fields = ("tenant",)


class CorporateCardAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "label", "currency", "external_ref")
    list_filter = ("tenant", "currency")
    search_fields = ("label", "external_ref")
    autocomplete_fields = ("tenant",)


class WalletAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "wallet_type",
        "currency",
        "opening_balance",
        "is_visible_in_cash_section",
    )
    list_filter = ("tenant", "wallet_type", "currency")
    raw_id_fields = ("tenant", "cash_register", "bank_account", "corporate_card_account")


register_portal(CashRegister, "Касса (кошелёк)", "Кассы", CashRegisterAdmin)
register_portal(BankAccount, "Банковский счёт", "Банковские счета", BankAccountAdmin)
register_portal(CorporateCardAccount, "Счёт корпкарты", "Счета корпкарт", CorporateCardAccountAdmin)
register_portal(Wallet, "Кошелёк", "Кошельки", WalletAdmin)
