from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.modules.wallets.models import BankAccount
from apps.modules.wallets.resolution import get_or_create_bank_wallet, get_or_create_bank_wallet_for_account
from apps.modules.wallets.serializers import BankAccountSerializer
from apps.tenants.models import Tenant

ACCOUNT_NO = "20208840000000000001"


class BankAccountTypeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

    def test_existing_and_default_accounts_are_controlled(self):
        ba = BankAccount.objects.create(tenant=self.tenant, label="X", account_no="1", mfo="2")
        self.assertEqual(ba.account_type, "controlled")
        other = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True)
        wallet = get_or_create_bank_wallet(tenant=other)
        self.assertEqual(wallet.bank_account.account_type, "controlled")

    def test_wallet_for_account_takes_currency_and_type_on_create(self):
        wallet = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no=ACCOUNT_NO, mfo="01158", currency="USD", account_type="informational"
        )
        self.assertEqual(wallet.currency, "USD")
        self.assertEqual(wallet.bank_account.account_type, "informational")

    def test_wallet_for_account_keeps_existing_rows(self):
        first = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no=ACCOUNT_NO, mfo="01158", currency="USD", account_type="informational"
        )
        second = get_or_create_bank_wallet_for_account(
            tenant=self.tenant, account_no=ACCOUNT_NO, mfo="01158", currency="EUR", account_type="controlled"
        )
        self.assertEqual(first.pk, second.pk)
        second.refresh_from_db()
        second.bank_account.refresh_from_db()
        self.assertEqual(second.currency, "USD")
        self.assertEqual(second.bank_account.account_type, "informational")

    def test_currency_defaults_to_uzs(self):
        wallet = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no=ACCOUNT_NO, mfo="01158")
        self.assertEqual(wallet.currency, "UZS")
        self.assertEqual(wallet.bank_account.account_type, "controlled")

    def test_serializer_exposes_type_read_only(self):
        ba = BankAccount.objects.create(tenant=self.tenant, label="X", account_no=ACCOUNT_NO, mfo="01158")
        self.assertEqual(BankAccountSerializer(ba).data["account_type"], "controlled")
        ser = BankAccountSerializer(ba, data={"account_type": "informational"}, partial=True)
        self.assertTrue(ser.is_valid(), ser.errors)
        ser.save()
        ba.refresh_from_db()
        self.assertEqual(ba.account_type, "controlled")


class MigrationsInSyncTests(TestCase):
    def test_no_missing_migrations_for_wallets(self):
        out = StringIO()
        try:
            call_command("makemigrations", "wallets", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"wallets models and migrations are out of sync:\n{out.getvalue()}")
