from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.modules.kapitalbank.fixtures import ACCOUNT_1, KapitalbankFixtures
from apps.modules.kapitalbank.models import BankAccountLink, KapitalbankAlertSettings, KapitalbankConnection


class KapitalbankModelsTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _link(self, **kwargs):
        data = {"tenant": self.tenant, "account_no": ACCOUNT_1, "branch": "01158"}
        data.update(kwargs)
        return BankAccountLink(**data)

    def test_password_roundtrip_and_not_stored_plain(self):
        c = KapitalbankConnection(tenant=self.tenant, login="user")
        self.assertFalse(c.has_password)
        c.set_password("p:a@ss Ж")
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.get_password(), "p:a@ss Ж")
        self.assertNotIn("p:a@ss", c.password_enc)
        self.assertTrue(c.has_password)

    def test_link_linked_requires_exactly_one_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._link(decision=BankAccountLink.LINKED).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._link(
                decision=BankAccountLink.LINKED, bank_account=self.bank_account1, card_account=self.card_account
            ).save()
        ok = self._link(decision=BankAccountLink.LINKED, bank_account=self.bank_account1)
        ok.save()
        self.assertEqual(ok.wallet(), self.wallet1)
        self.assertFalse(ok.is_card)

    def test_link_card_target_is_card(self):
        link = self._link(decision=BankAccountLink.LINKED, card_account=self.card_account)
        link.save()
        self.assertTrue(link.is_card)
        self.assertEqual(link.wallet(), self.card_wallet)

    def test_link_ignored_requires_reason(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._link(decision=BankAccountLink.IGNORED, ignore_reason="").save()
        self._link(decision=BankAccountLink.IGNORED, ignore_reason="не наш счёт").save()

    def test_link_pending_requires_no_targets(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._link(decision=BankAccountLink.PENDING, bank_account=self.bank_account1).save()
        self._link().save()

    def test_link_unique_per_tenant_account_branch(self):
        self._link().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._link().save()
        self._link(branch="09999").save()

    def test_alert_settings_singleton(self):
        a = KapitalbankAlertSettings.load()
        b = KapitalbankAlertSettings.load()
        self.assertEqual(a.pk, 1)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(KapitalbankAlertSettings.objects.count(), 1)


class MigrationsInSyncTests(TestCase):
    def test_no_missing_migrations_for_kapitalbank(self):
        out = StringIO()
        try:
            call_command("makemigrations", "kapitalbank", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"kapitalbank models and migrations are out of sync:\n{out.getvalue()}")
