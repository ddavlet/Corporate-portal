# Data migration: create anchors/wallets and set wallet_id on all movement rows.

from django.db import migrations


def _norm_currency(raw):
    c = (raw or "").strip()
    return c if c else "UZS"


def forwards(apps, schema_editor):
    CashRegister = apps.get_model("wallets", "CashRegister")
    BankAccount = apps.get_model("wallets", "BankAccount")
    CorporateCardAccount = apps.get_model("wallets", "CorporateCardAccount")
    Wallet = apps.get_model("wallets", "Wallet")
    CashExpense = apps.get_model("cashier", "CashExpense")
    CashRevenue = apps.get_model("cashier", "CashRevenue")
    BankExpense = apps.get_model("bank_expenses", "BankExpense")
    BankRevenue = apps.get_model("bank_expenses", "BankRevenue")
    CardExpense = apps.get_model("corporate_card", "CardExpense")
    CardRevenue = apps.get_model("corporate_card", "CardRevenue")

    def cash_wallet_for(tenant_id: int, currency: str):
        cur = _norm_currency(currency)
        reg, _ = CashRegister.objects.get_or_create(
            tenant_id=tenant_id,
            currency=cur,
            defaults={
                "name": "Основная",
                "is_active": True,
                "is_default_for_currency": True,
            },
        )
        w, _ = Wallet.objects.get_or_create(
            cash_register_id=reg.id,
            defaults={
                "tenant_id": tenant_id,
                "wallet_type": "cash",
                "currency": cur,
                "opening_balance": 0,
            },
        )
        return w

    def corp_wallet_for(tenant_id: int, currency: str):
        cur = _norm_currency(currency)
        acc, _ = CorporateCardAccount.objects.get_or_create(
            tenant_id=tenant_id,
            currency=cur,
            defaults={"label": "Основная"},
        )
        w, _ = Wallet.objects.get_or_create(
            corporate_card_account_id=acc.id,
            defaults={
                "tenant_id": tenant_id,
                "wallet_type": "corporate_card",
                "currency": cur,
                "opening_balance": 0,
            },
        )
        return w

    bank_wallet_cache: dict[int, int] = {}

    def bank_wallet_id_for(tenant_id: int) -> int:
        if tenant_id in bank_wallet_cache:
            return bank_wallet_cache[tenant_id]
        ba, _ = BankAccount.objects.get_or_create(
            tenant_id=tenant_id,
            defaults={"label": "Основной", "account_no": "", "mfo": ""},
        )
        w, _ = Wallet.objects.get_or_create(
            bank_account_id=ba.id,
            defaults={
                "tenant_id": tenant_id,
                "wallet_type": "bank",
                "currency": "UZS",
                "opening_balance": 0,
            },
        )
        bank_wallet_cache[tenant_id] = w.id
        return w.id

    # Cash
    for row in CashExpense.objects.filter(wallet_id__isnull=True).iterator():
        w = cash_wallet_for(row.tenant_id, row.currency)
        CashExpense.objects.filter(pk=row.pk).update(wallet_id=w.id)

    for row in CashRevenue.objects.filter(wallet_id__isnull=True).iterator():
        w = cash_wallet_for(row.tenant_id, row.currency)
        CashRevenue.objects.filter(pk=row.pk).update(wallet_id=w.id)

    # Corporate card
    for row in CardExpense.objects.filter(wallet_id__isnull=True).iterator():
        w = corp_wallet_for(row.tenant_id, row.currency)
        CardExpense.objects.filter(pk=row.pk).update(wallet_id=w.id)

    for row in CardRevenue.objects.filter(wallet_id__isnull=True).iterator():
        w = corp_wallet_for(row.tenant_id, row.currency)
        CardRevenue.objects.filter(pk=row.pk).update(wallet_id=w.id)

    # Bank (single wallet per tenant)
    for row in BankExpense.objects.filter(wallet_id__isnull=True).iterator():
        wid = bank_wallet_id_for(row.tenant_id)
        BankExpense.objects.filter(pk=row.pk).update(wallet_id=wid)

    for row in BankRevenue.objects.filter(wallet_id__isnull=True).iterator():
        wid = bank_wallet_id_for(row.tenant_id)
        BankRevenue.objects.filter(pk=row.pk).update(wallet_id=wid)


def backwards(apps, schema_editor):
    CashExpense = apps.get_model("cashier", "CashExpense")
    CashRevenue = apps.get_model("cashier", "CashRevenue")
    BankExpense = apps.get_model("bank_expenses", "BankExpense")
    BankRevenue = apps.get_model("bank_expenses", "BankRevenue")
    CardExpense = apps.get_model("corporate_card", "CardExpense")
    CardRevenue = apps.get_model("corporate_card", "CardRevenue")
    for Model in (CashExpense, CashRevenue, BankExpense, BankRevenue, CardExpense, CardRevenue):
        Model.objects.all().update(wallet_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("wallets", "0001_initial"),
        ("cashier", "0007_cashexpense_wallet_cashrevenue_wallet"),
        ("bank_expenses", "0011_bankexpense_wallet_bankrevenue_wallet"),
        ("corporate_card", "0003_cardexpense_wallet_cardrevenue_wallet"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
