import datetime as dt
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, gateway_ok
from apps.modules.kapitalbank import classification
from apps.modules.kapitalbank.classification import (
    ClassificationError,
    attach_bank,
    attach_card,
    classify,
    kind_for_account,
    set_account_type,
)
from apps.modules.kapitalbank.fixtures import ACCOUNT_1, MFO, KapitalbankFixtures
from apps.modules.kapitalbank.models import BankAccountLink, KapitalbankAlertSettings, SyncEvent
from apps.modules.wallets.models import BankAccount, CorporateCardAccount, Wallet

NOW = dt.datetime(2026, 10, 30, 10, 0, tzinfo=dt.timezone.utc)
TODAY = dt.date(2026, 10, 30)
USD_ACCOUNT = "20208840000000000001"
UZS_ACCOUNT = "20208000000000000001"
CARD_ACCOUNT = "22620000000000000001"
SERVICE_ACCOUNT = "16401000000000000001"
MISSING = "99999000000000000001"

CONTROLLED = BankAccount.AccountType.CONTROLLED
INFORMATIONAL = BankAccount.AccountType.INFORMATIONAL
SERVICE = BankAccount.AccountType.SERVICE


class KindForAccountTests(TestCase):
    def test_kind_for_account_rules(self):
        cases = [
            ("22620000000000000001", "", classification.KIND_CARD),
            ("16401000000000000001", "", classification.KIND_SERVICE),
            ("23510000000000000001", "", classification.KIND_SERVICE),
            ("22613000000000000001", "", classification.KIND_SERVICE),
            ("23106000000000000001", "", classification.KIND_SERVICE),
            ("22614840000000000001", "USD", classification.KIND_INFORMATIONAL),
            ("20208840000000000001", "USD", classification.KIND_INFORMATIONAL),
            ("20208000000000000001", "UZS", classification.KIND_CONTROLLED),
            ("20208000000000000001", "", classification.KIND_CONTROLLED),
            ("20210000000000000001", "UZS", classification.KIND_CONTROLLED),
            ("29801000000000000001", "", classification.KIND_CONTROLLED),
        ]
        for account_no, currency, kind in cases:
            with self.subTest(account_no=account_no, currency=currency):
                self.assertEqual(kind_for_account(account_no, currency), kind)
        self.assertEqual(
            (classification.KIND_CONTROLLED, classification.KIND_INFORMATIONAL, classification.KIND_SERVICE),
            (CONTROLLED, INFORMATIONAL, SERVICE),
        )
        self.assertEqual(classification.KIND_CARD, "card")


class ClassificationTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        settings_obj = KapitalbankAlertSettings.load()
        settings_obj.recipient = self.owner
        settings_obj.save()
        patcher = patch(GATEWAY_PATH)
        self.gw = patcher.start()
        self.gw.side_effect = gateway_ok()
        self.addCleanup(patcher.stop)

    def _link(self, account_no, *, branch=MFO, currency="", **kw):
        return BankAccountLink.objects.create(
            tenant=self.tenant, account_no=account_no, branch=branch, name=f"Счёт {account_no[-4:]}",
            currency=currency, **kw
        )

    def _type_events(self):
        return SyncEvent.objects.filter(kind=SyncEvent.ALERT_TYPE_CHANGED)

    def test_attach_bank_creates_wallet_in_bank_currency(self):
        link = self._link(USD_ACCOUNT, currency="USD")

        wallet = attach_bank(link, account_type=INFORMATIONAL, today=TODAY, now=NOW, user=self.owner)

        self.assertEqual(wallet.currency, "USD")
        self.assertEqual(wallet.wallet_type, Wallet.Type.BANK)
        self.assertEqual(wallet.bank_account.account_no, USD_ACCOUNT)
        self.assertEqual(wallet.bank_account.mfo, MFO)
        self.assertEqual(wallet.bank_account.account_type, INFORMATIONAL)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.LINKED)
        self.assertEqual(link.bank_account, wallet.bank_account)
        self.assertEqual(link.track_from, TODAY)
        self.assertIsNone(link.opening_synced_at)
        self.assertEqual(link.decided_at, NOW)
        self.assertEqual(link.decided_by, self.owner)
        # created with its type: no type-change message
        self.assertFalse(self._type_events().exists())
        with self.assertRaises(ClassificationError):
            attach_bank(link, account_type=INFORMATIONAL, today=TODAY, now=NOW)

    def test_attach_bank_reuses_account_and_sets_its_type(self):
        link = self._link(ACCOUNT_1)  # the fixture's portal account (controlled, no movements)

        wallet = attach_bank(link, account_type=INFORMATIONAL, today=TODAY, now=NOW)

        self.assertEqual(wallet, self.wallet1)
        self.bank_account1.refresh_from_db()
        self.assertEqual(self.bank_account1.account_type, INFORMATIONAL)
        self.assertEqual(self._type_events().count(), 1)
        self.assertEqual(self._type_events().get().link, link)

    def test_attach_bank_refuses_account_linked_elsewhere(self):
        self._link(ACCOUNT_1, branch=MFO, decision=BankAccountLink.LINKED, bank_account=self.bank_account1)
        BankAccount.objects.filter(pk=self.bank_account1.pk).update(mfo="00014")
        other = self._link(ACCOUNT_1, branch="00014")

        with self.assertRaises(ClassificationError):
            attach_bank(other, account_type=CONTROLLED, today=TODAY, now=NOW)

        other.refresh_from_db()
        self.assertEqual(other.decision, BankAccountLink.PENDING)
        self.assertIsNone(other.track_from)

    def test_attach_bank_refuses_reused_account_with_movements(self):
        BankExpense.objects.create(
            tenant=self.tenant,
            created_by_id=1,
            row_no=1,
            doc_date=TODAY - dt.timedelta(days=30),
            process_date=TODAY - dt.timedelta(days=30),
            expense_year=TODAY.year,
            expense_month=9,
            expense_day=30,
            doc_no="1",
            debit_turnover=Decimal("100.00"),
            payment_purpose="Оплата",
            wallet=self.wallet1,
        )
        link = self._link(ACCOUNT_1)

        with self.assertRaisesMessage(ClassificationError, "уже есть движения"):
            attach_bank(link, account_type=CONTROLLED, today=TODAY, now=NOW)

        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)
        self.assertIsNone(link.bank_account)

    def test_attach_card_creates_corporate_card_account(self):
        link = self._link(CARD_ACCOUNT, currency="UZS")

        wallet = attach_card(link, today=TODAY, now=NOW)

        card = wallet.corporate_card_account
        self.assertEqual(card.external_ref, CARD_ACCOUNT)
        self.assertEqual(card.label, link.name)
        self.assertEqual(card.currency, "UZS")
        self.assertEqual(wallet.wallet_type, Wallet.Type.CORPORATE_CARD)
        self.assertEqual(wallet.currency, "UZS")
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.LINKED)
        self.assertEqual(link.card_account, card)
        self.assertEqual(link.track_from, TODAY)
        self.assertIsNone(link.opening_synced_at)

        again = self._link(CARD_ACCOUNT, branch="00014", currency="UZS")
        self.assertEqual(attach_card(again, today=TODAY, now=NOW), wallet)
        self.assertEqual(CorporateCardAccount.objects.filter(external_ref=CARD_ACCOUNT).count(), 1)

    def test_set_account_type_alerts_once_per_change(self):
        self._link(ACCOUNT_1, decision=BankAccountLink.LINKED, bank_account=self.bank_account1)

        self.assertTrue(set_account_type(self.bank_account1, INFORMATIONAL, now=NOW))

        self.bank_account1.refresh_from_db()
        self.assertEqual(self.bank_account1.account_type, INFORMATIONAL)
        event = self._type_events().get()
        self.assertEqual(event.payload["old"], CONTROLLED)
        self.assertEqual(event.payload["new"], INFORMATIONAL)
        self.assertIsNone(event.payload["changed_by"])
        text = self.gw.call_args.kwargs["payload"]["text"]
        self.assertIn("Смена типа счёта", text)
        self.assertIn("Kolberg Plus", text)
        self.assertIn(ACCOUNT_1, text)
        self.assertIn("Контролируемый → Информационный", text)
        self.assertIn("команда", text)

        self.assertFalse(set_account_type(self.bank_account1, INFORMATIONAL, now=NOW))
        self.assertEqual(self._type_events().count(), 1)
        self.assertEqual(self.gw.call_count, 1)

    def test_set_account_type_without_link(self):
        # like n8n's synthetic default account: no number, no Kapitalbank link
        synthetic = BankAccount.objects.create(tenant=self.tenant, label="Основной", account_no="", mfo="")

        self.assertTrue(set_account_type(synthetic, SERVICE, changed_by=self.owner, now=NOW))

        synthetic.refresh_from_db()
        self.assertEqual(synthetic.account_type, SERVICE)
        event = self._type_events().get()
        self.assertIsNone(event.link)
        self.assertEqual(event.tenant, self.tenant)
        self.assertEqual(event.payload["changed_by"], self.owner.pk)
        self.assertIn("Владелец", event.message)

    def _run(self, *args):
        out = StringIO()
        call_command("classify_kapitalbank_accounts", f"--tenant={self.tenant.subdomain}", *args, stdout=out)
        return out.getvalue()

    def test_classify_command_dry_run_and_apply(self):
        pending = self._link(UZS_ACCOUNT, currency="UZS")
        service = self._link(SERVICE_ACCOUNT)
        linked = self._link(ACCOUNT_1, decision=BankAccountLink.LINKED, bank_account=self.bank_account1)

        out = self._run(f"--account={UZS_ACCOUNT},{MISSING}", "--type=controlled")
        self.assertIn("(dry-run)", out)
        self.assertIn("would_attach=1 would_set_type=0 skipped=1", out)
        self.assertIn(f"{MISSING} | | | | пропущен", out)

        # PENDING + service is left for ignore-kapitalbank; LINKED bank gets the new type
        out = self._run(f"--account={SERVICE_ACCOUNT},{ACCOUNT_1}", "--type=service")
        self.assertIn("would_attach=0 would_set_type=1 skipped=1", out)
        self.assertIn("ignore-kapitalbank", out)

        # the dry run wrote nothing and sent nothing
        pending.refresh_from_db()
        self.assertEqual(pending.decision, BankAccountLink.PENDING)
        self.assertFalse(BankAccount.objects.filter(account_no=UZS_ACCOUNT).exists())
        self.bank_account1.refresh_from_db()
        self.assertEqual(self.bank_account1.account_type, CONTROLLED)
        self.assertFalse(self._type_events().exists())
        self.assertEqual(self.gw.call_count, 0)

        out = self._run(f"--account={UZS_ACCOUNT},{MISSING},{ACCOUNT_1}", "--type=controlled", "--apply")
        self.assertIn("attached=1 type_changed=0 skipped=2", out)  # MISSING, ACCOUNT_1 already controlled
        pending.refresh_from_db()
        self.assertEqual(pending.decision, BankAccountLink.LINKED)
        self.assertEqual(pending.track_from, timezone.localdate())
        self.assertIsNone(pending.opening_synced_at)
        self.assertEqual(pending.bank_account.account_type, CONTROLLED)
        self.assertEqual(pending.bank_account.wallet.currency, "UZS")

        out = self._run(f"--account={SERVICE_ACCOUNT},{ACCOUNT_1}", "--type=service", "--apply")
        self.assertIn("attached=0 type_changed=1 skipped=1", out)
        service.refresh_from_db()
        self.assertEqual(service.decision, BankAccountLink.PENDING)
        linked.refresh_from_db()
        self.assertEqual(linked.decision, BankAccountLink.LINKED)
        self.assertEqual(linked.bank_account, self.bank_account1)
        self.bank_account1.refresh_from_db()
        self.assertEqual(self.bank_account1.account_type, SERVICE)
        self.assertEqual(self._type_events().count(), 1)
        self.assertEqual(self._type_events().get().link, linked)

        for args in (
            (f"--account={UZS_ACCOUNT}", "--type=bogus"),
            (f"--account={UZS_ACCOUNT}", "--type=card"),
            ("--account=2020-1", "--type=controlled"),
        ):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self._run(*args, "--apply")

    def test_classify_skips_card_and_ignored_links(self):
        card = self._link(CARD_ACCOUNT)
        attach_card(card, today=TODAY, now=NOW)
        ignored = self._link(SERVICE_ACCOUNT, decision=BankAccountLink.IGNORED, ignore_reason="Комиссии")

        results = classify(
            tenant=self.tenant, account_nos=[CARD_ACCOUNT, SERVICE_ACCOUNT], account_type=CONTROLLED,
            apply=True, today=TODAY, now=NOW,
        )

        self.assertEqual(
            [(r.action, r.skip_reason, r.done) for r in results],
            [
                (classification.ACTION_SKIP, classification.CARD_LINKED, False),
                (classification.ACTION_SKIP, classification.IGNORED, False),
            ],
        )
        ignored.refresh_from_db()
        self.assertEqual(ignored.decision, BankAccountLink.IGNORED)

    def test_classify_refuses_card_account_as_bank(self):
        link = self._link(CARD_ACCOUNT, currency="UZS")

        for account_type in (CONTROLLED, INFORMATIONAL):
            with self.subTest(account_type=account_type):
                results = classify(
                    tenant=self.tenant, account_nos=[CARD_ACCOUNT], account_type=account_type,
                    apply=False, today=TODAY, now=NOW,
                )
                self.assertEqual(
                    [(r.action, r.skip_reason, r.done) for r in results],
                    [(classification.ACTION_ATTACH, classification.CARD_ACCOUNT, False)],
                )
        out = self._run(f"--account={CARD_ACCOUNT}", "--type=controlled", "--apply")
        self.assertIn("attached=0 type_changed=0 skipped=1", out)
        self.assertIn("Корпоративные карты", out)

        with self.assertRaisesMessage(ClassificationError, "Корпоративные карты"):
            attach_bank(link, account_type=CONTROLLED, today=TODAY, now=NOW)

        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)
        self.assertIsNone(link.bank_account)
        self.assertFalse(BankAccount.objects.filter(account_no=CARD_ACCOUNT).exists())
        self.assertFalse(self._type_events().exists())
