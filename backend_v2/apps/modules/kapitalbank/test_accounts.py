from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase

from apps.modules.kapitalbank.accounts import currency_letters, pending_accounts, refresh_account_list
from apps.modules.kapitalbank.client import BankListedAccount
from apps.modules.kapitalbank.fixtures import ACCOUNT_1, ACCOUNT_2, MFO, KapitalbankFixtures
from apps.modules.kapitalbank.models import BankAccountLink, KapitalbankConnection

NEW_ACCOUNT = "20208000904843803009"


class StubClient:
    def __init__(self, accounts):
        self._accounts = accounts

    def list_accounts(self):
        return self._accounts


def listed(account_no, balance="100.00", currency="000"):
    return BankListedAccount(
        account_no=account_no,
        branch=MFO,
        name="Расчетный счет",
        currency=currency,
        state_name="Открыт",
        balance=Decimal(balance),
    )


class RefreshAccountListTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.connection = KapitalbankConnection.objects.create(tenant=self.tenant, login="IB#u", is_enabled=True)
        self.now = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)

    def test_new_account_is_pending_and_existing_decision_untouched(self):
        existing = BankAccountLink.objects.create(
            tenant=self.tenant,
            account_no=ACCOUNT_1,
            branch=MFO,
            decision=BankAccountLink.LINKED,
            bank_account=self.bank_account1,
            decided_by=self.owner,
            decided_at=self.now,
            last_balance=Decimal("1.00"),
        )
        refresh_account_list(
            self.connection, StubClient([listed(ACCOUNT_1, "460000.00"), listed(NEW_ACCOUNT)]), now=self.now
        )
        existing.refresh_from_db()
        self.assertEqual(existing.decision, BankAccountLink.LINKED)
        self.assertEqual(existing.bank_account_id, self.bank_account1.pk)
        self.assertEqual(existing.decided_by_id, self.owner.pk)
        self.assertEqual(existing.last_balance, Decimal("460000.00"))
        self.assertEqual(existing.last_seen_at, self.now)
        new = BankAccountLink.objects.get(tenant=self.tenant, account_no=NEW_ACCOUNT)
        self.assertEqual(new.decision, BankAccountLink.PENDING)
        self.assertEqual(new.first_seen_at, self.now)

    def test_nothing_linked_automatically(self):
        # ACCOUNT_2 already exists as a BankAccount in the portal.
        refresh_account_list(self.connection, StubClient([listed(ACCOUNT_2)]), now=self.now)
        link = BankAccountLink.objects.get(tenant=self.tenant, account_no=ACCOUNT_2)
        self.assertEqual(link.decision, BankAccountLink.PENDING)
        self.assertIsNone(link.bank_account)

    def test_vanished_account_is_left_alone_and_pending_list(self):
        refresh_account_list(self.connection, StubClient([listed(ACCOUNT_1)]), now=self.now)
        refresh_account_list(self.connection, StubClient([]), now=self.now)
        self.assertEqual(BankAccountLink.objects.count(), 1)
        self.assertEqual(list(pending_accounts(self.tenant).values_list("account_no", flat=True)), [ACCOUNT_1])

    def test_numeric_currency_codes_are_stored_as_letters(self):
        self.assertEqual(
            [currency_letters(c) for c in ("000", "860", "840", "978", "643", "999", "")],
            ["UZS", "UZS", "USD", "EUR", "RUB", "999", ""],
        )
        existing = BankAccountLink.objects.create(tenant=self.tenant, account_no=ACCOUNT_1, branch=MFO, currency="000")
        refresh_account_list(
            self.connection,
            StubClient([listed(ACCOUNT_1), listed(ACCOUNT_2, currency="840"), listed(NEW_ACCOUNT, currency="392")]),
            now=self.now,
        )
        existing.refresh_from_db()
        self.assertEqual(existing.currency, "UZS")
        currencies = dict(BankAccountLink.objects.values_list("account_no", "currency"))
        self.assertEqual(currencies[ACCOUNT_2], "USD")
        self.assertEqual(currencies[NEW_ACCOUNT], "392")
