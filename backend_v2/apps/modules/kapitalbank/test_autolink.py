import datetime as dt
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.kapitalbank import autolink
from apps.modules.kapitalbank.autolink import auto_link_pending
from apps.modules.kapitalbank.fixtures import ACCOUNT_1, ACCOUNT_2, CARD_REF, MFO, KapitalbankFixtures
from apps.modules.kapitalbank.models import BankAccountLink
from apps.modules.wallets.models import BankAccount, CorporateCardAccount
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account
from apps.tenants.models import Tenant

NOW = dt.datetime(2026, 10, 27, 10, 0, tzinfo=dt.timezone.utc)
OTHER_ACCOUNT = "20208000305425326002"


class AutoLinkPendingTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _pending(self, account_no, branch=MFO, tenant=None):
        return BankAccountLink.objects.create(
            tenant=tenant or self.tenant, account_no=account_no, branch=branch, name=f"Счёт {account_no[-4:]}"
        )

    def test_dry_run_plans_exact_matches_and_writes_nothing(self):
        bank_link = self._pending(ACCOUNT_1)
        card_link = self._pending(CARD_REF)

        results = {r.link.pk: r for r in auto_link_pending(apply=False, now=NOW)}

        self.assertEqual(results[bank_link.pk].bank_account, self.bank_account1)
        self.assertIsNone(results[bank_link.pk].card_account)
        self.assertEqual(results[card_link.pk].card_account, self.card_account)
        self.assertIsNone(results[card_link.pk].bank_account)
        self.assertTrue(all(r.matched and not r.linked for r in results.values()))
        self.assertEqual(
            set(BankAccountLink.objects.values_list("decision", flat=True)), {BankAccountLink.PENDING}
        )

    def test_apply_links_bank_by_number_and_mfo_and_card_by_external_ref(self):
        bank_link = self._pending(ACCOUNT_2)
        card_link = self._pending(CARD_REF)

        results = auto_link_pending(apply=True, now=NOW)

        self.assertTrue(all(r.linked for r in results))
        bank_link.refresh_from_db()
        card_link.refresh_from_db()
        self.assertEqual(bank_link.decision, BankAccountLink.LINKED)
        self.assertEqual(bank_link.bank_account, self.bank_account2)
        self.assertIsNone(bank_link.card_account)
        self.assertEqual(bank_link.decided_at, NOW)
        self.assertIsNone(bank_link.decided_by)
        self.assertEqual(bank_link.wallet(), self.wallet2)
        self.assertEqual(card_link.decision, BankAccountLink.LINKED)
        self.assertEqual(card_link.card_account, self.card_account)
        self.assertEqual(card_link.wallet(), self.card_wallet)

    def test_account_of_another_tenant_is_not_linked(self):
        # lemonfit and lemonhavo share one bank login: lemonfit sees lemonhavo's account.
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        get_or_create_bank_wallet_for_account(tenant=other, account_no=OTHER_ACCOUNT, mfo=MFO)
        link = self._pending(OTHER_ACCOUNT)

        [result] = auto_link_pending(apply=True, now=NOW)

        self.assertEqual(result.skip_reason, autolink.NO_MATCH)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)
        self.assertIsNone(link.bank_account)

    def test_mfo_mismatch_is_not_linked(self):
        link = self._pending(ACCOUNT_1, branch="00365")

        [result] = auto_link_pending(apply=True, now=NOW)

        self.assertEqual(result.skip_reason, autolink.NO_MATCH)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)

    def test_card_without_external_ref_is_not_linked(self):
        # neuron: the portal card account has an empty external_ref.
        CorporateCardAccount.objects.filter(pk=self.card_account.pk).update(external_ref="")
        link = self._pending(CARD_REF)

        [result] = auto_link_pending(apply=True, now=NOW)

        self.assertEqual(result.skip_reason, autolink.NO_MATCH)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)

    def test_bank_and_card_with_same_number_is_ambiguous(self):
        CorporateCardAccount.objects.filter(pk=self.card_account.pk).update(external_ref=ACCOUNT_1)
        link = self._pending(ACCOUNT_1)

        [result] = auto_link_pending(apply=True, now=NOW)

        self.assertEqual(result.skip_reason, autolink.SEVERAL_MATCHES)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)

    def test_portal_account_already_linked_is_not_reused(self):
        CorporateCardAccount.objects.filter(pk=self.card_account.pk).update(external_ref=ACCOUNT_2)
        BankAccountLink.objects.create(
            tenant=self.tenant,
            account_no=ACCOUNT_2,
            branch="00365",
            decision=BankAccountLink.LINKED,
            card_account=self.card_account,
        )
        card_link = self._pending(ACCOUNT_2, branch="00444")

        [result] = auto_link_pending(apply=True, now=NOW)

        self.assertEqual(result.link, card_link)
        self.assertEqual(result.skip_reason, autolink.ALREADY_LINKED)
        card_link.refresh_from_db()
        self.assertEqual(card_link.decision, BankAccountLink.PENDING)

    def test_two_bank_accounts_matching_one_card_are_both_left_pending(self):
        first = self._pending(CARD_REF, branch="01158")
        second = self._pending(CARD_REF, branch="00365")

        results = auto_link_pending(apply=True, now=NOW)

        self.assertEqual({r.skip_reason for r in results}, {autolink.SHARED_MATCH})
        for link in (first, second):
            link.refresh_from_db()
            self.assertEqual(link.decision, BankAccountLink.PENDING)

    def test_portal_account_without_wallet_is_not_linked(self):
        BankAccount.objects.create(tenant=self.tenant, label="Без кошелька", account_no=OTHER_ACCOUNT, mfo=MFO)
        link = self._pending(OTHER_ACCOUNT)

        [result] = auto_link_pending(apply=True, now=NOW)

        self.assertEqual(result.skip_reason, autolink.NO_WALLET)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)

    def test_decided_links_are_untouched(self):
        ignored = BankAccountLink.objects.create(
            tenant=self.tenant,
            account_no=ACCOUNT_1,
            branch=MFO,
            decision=BankAccountLink.IGNORED,
            ignore_reason="ведётся в другом тенанте",
        )

        self.assertEqual(auto_link_pending(apply=True, now=NOW), [])

        ignored.refresh_from_db()
        self.assertEqual(ignored.decision, BankAccountLink.IGNORED)
        self.assertIsNone(ignored.bank_account)

    def test_tenant_filter(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        get_or_create_bank_wallet_for_account(tenant=other, account_no=OTHER_ACCOUNT, mfo=MFO)
        other_link = self._pending(OTHER_ACCOUNT, tenant=other)
        own_link = self._pending(ACCOUNT_1)

        results = auto_link_pending(tenant=self.tenant, apply=True, now=NOW)

        self.assertEqual([r.link for r in results], [own_link])
        other_link.refresh_from_db()
        self.assertEqual(other_link.decision, BankAccountLink.PENDING)


class LinkKapitalbankAccountsCommandTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.link = BankAccountLink.objects.create(tenant=self.tenant, account_no=ACCOUNT_1, branch=MFO)
        self.unmatched = BankAccountLink.objects.create(tenant=self.tenant, account_no=OTHER_ACCOUNT, branch=MFO)

    def _call(self, *args):
        out = StringIO()
        call_command("link_kapitalbank_accounts", *args, stdout=out)
        return out.getvalue()

    def test_default_is_dry_run(self):
        out = self._call("--tenant", "kp")

        self.assertIn("(dry-run)", out)
        self.assertIn(f"{ACCOUNT_1} | {MFO} |", out)
        self.assertIn("будет привязан к банковский счёт портала", out)
        self.assertIn("would_link=1 left_pending=1", out)
        self.link.refresh_from_db()
        self.assertEqual(self.link.decision, BankAccountLink.PENDING)

    def test_apply_writes_only_matches(self):
        out = self._call("--apply")

        self.assertIn("linked=1 left_pending=1", out)
        self.link.refresh_from_db()
        self.unmatched.refresh_from_db()
        self.assertEqual(self.link.decision, BankAccountLink.LINKED)
        self.assertEqual(self.link.bank_account, self.bank_account1)
        self.assertEqual(self.unmatched.decision, BankAccountLink.PENDING)

    def test_unknown_tenant(self):
        with self.assertRaises(CommandError):
            self._call("--tenant", "nope", "--apply")
        self.link.refresh_from_db()
        self.assertEqual(self.link.decision, BankAccountLink.PENDING)
