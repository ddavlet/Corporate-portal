from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.modules.kapitalbank.admin import BankAccountLinkForm
from apps.modules.kapitalbank.fixtures import ACCOUNT_1, KapitalbankFixtures
from apps.modules.kapitalbank.models import (
    BankAccountLink,
    KapitalbankAlertSettings,
    KapitalbankConnection,
    SyncEvent,
)
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account
from apps.tenants.models import Tenant

User = get_user_model()
SECRET = "Zx9-very-secret-pw"


class KapitalbankAdminTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.admin_user = User.objects.create_superuser(username="kb-root", password="x", full_name="Root")
        self.client.force_login(self.admin_user)

    def _conn(self):
        c = KapitalbankConnection(tenant=self.tenant, login="bank-user")
        c.set_password(SECRET)
        c.save()
        return c

    def test_password_never_rendered(self):
        c = self._conn()
        for url in (
            reverse("admin:kapitalbank_kapitalbankconnection_change", args=[c.pk]),
            reverse("admin:kapitalbank_kapitalbankconnection_changelist"),
        ):
            body = self.client.get(url).content.decode()
            self.assertNotIn(SECRET, body)
            self.assertNotIn(c.password_enc, body)
            self.assertNotIn("password_enc", body)
        self.assertIn("задан", self.client.get(reverse("admin:kapitalbank_kapitalbankconnection_changelist")).content.decode())

    def _post_conn(self, c, password):
        return self.client.post(
            reverse("admin:kapitalbank_kapitalbankconnection_change", args=[c.pk]),
            {"tenant": self.tenant.pk, "login": "new-login", "password": password, "is_enabled": "on"},
        )

    def test_empty_password_keeps_existing(self):
        c = self._conn()
        self.assertEqual(self._post_conn(c, "").status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.login, "new-login")
        self.assertEqual(c.get_password(), SECRET)

    def test_nonempty_password_replaces_and_not_in_history(self):
        c = self._conn()
        self.assertEqual(self._post_conn(c, "another-pw-1").status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.get_password(), "another-pw-1")
        hist = self.client.get(reverse("admin:kapitalbank_kapitalbankconnection_history", args=[c.pk])).content.decode()
        self.assertNotIn("another-pw-1", hist)
        self.assertNotIn(c.password_enc, hist)

    def _link(self, **kw):
        data = {"tenant": self.tenant, "account_no": ACCOUNT_1, "branch": "01158"}
        data.update(kw)
        return BankAccountLink.objects.create(**data)

    def _link_data(self, **kw):
        data = {
            "decision": "linked",
            "ignore_reason": "",
            "bank_account": "",
            "card_account": "",
        }
        data.update(kw)
        return data

    def test_link_cannot_point_to_other_tenant_account(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        foreign = get_or_create_bank_wallet_for_account(tenant=other, account_no="20208000111111111001", mfo="01158")
        link = self._link()
        form = BankAccountLinkForm(self._link_data(bank_account=foreign.bank_account.pk), instance=link)
        self.assertFalse(form.is_valid())
        self.assertIn("bank_account", form.errors)
        # add form (tenant unknown on instance) is also rejected by clean()
        add_form = BankAccountLinkForm(
            {
                "tenant": self.tenant.pk,
                "account_no": "20208000999999999001",
                "branch": "01158",
                **self._link_data(bank_account=foreign.bank_account.pk),
            }
        )
        self.assertFalse(add_form.is_valid())
        self.assertIn("bank_account", add_form.errors)

    def test_link_accepts_own_tenant_account(self):
        form = BankAccountLinkForm(self._link_data(bank_account=self.bank_account1.pk), instance=self._link())
        self.assertTrue(form.is_valid(), form.errors)

    def test_ignored_requires_reason_in_form(self):
        form = BankAccountLinkForm(self._link_data(decision="ignored"), instance=self._link())
        self.assertFalse(form.is_valid())
        self.assertIn("ignore_reason", form.errors)

    def test_linked_requires_exactly_one_target(self):
        link = self._link()
        self.assertFalse(BankAccountLinkForm(self._link_data(), instance=link).is_valid())
        both = self._link_data(bank_account=self.bank_account1.pk, card_account=self.card_account.pk)
        self.assertFalse(BankAccountLinkForm(both, instance=link).is_valid())

    def test_decided_by_only_set_when_decision_changes(self):
        link = self._link()
        url = reverse("admin:kapitalbank_bankaccountlink_change", args=[link.pk])
        resp = self.client.post(url, self._link_data(bank_account=self.bank_account1.pk))
        self.assertEqual(resp.status_code, 302)
        link.refresh_from_db()
        self.assertEqual(link.decided_by, self.admin_user)
        first = link.decided_at
        self.assertIsNotNone(first)
        # unchanged resubmission keeps decided_at
        self.client.post(url, self._link_data(bank_account=self.bank_account1.pk))
        link.refresh_from_db()
        self.assertEqual(link.decided_at, first)

    def test_events_not_deletable_nor_addable(self):
        request = RequestFactory().get("/")
        request.user = self.admin_user
        ev_admin = site._registry[SyncEvent]
        self.assertFalse(ev_admin.has_delete_permission(request))
        self.assertFalse(ev_admin.has_add_permission(request))
        self.assertNotIn("delete_selected", ev_admin.get_actions(request))

    def test_events_default_last_30_days_with_all_option(self):
        from datetime import timedelta

        from django.utils import timezone

        new = SyncEvent.objects.create(tenant=self.tenant, kind="imported", message="fresh-evt")
        old = SyncEvent.objects.create(tenant=self.tenant, kind="imported", message="stale-evt")
        SyncEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=60))
        url = reverse("admin:kapitalbank_syncevent_changelist")
        body = self.client.get(url).content.decode()
        self.assertIn("fresh-evt", body)
        self.assertNotIn("stale-evt", body)
        body_all = self.client.get(url, {"period": "all"}).content.decode()
        self.assertIn("stale-evt", body_all)
        self.assertEqual(new.pk and 1, 1)

    def test_alert_settings_single_and_not_deletable(self):
        request = RequestFactory().get("/")
        request.user = self.admin_user
        s_admin = site._registry[KapitalbankAlertSettings]
        self.assertTrue(s_admin.has_add_permission(request))
        KapitalbankAlertSettings.load()
        self.assertFalse(s_admin.has_add_permission(request))
        self.assertFalse(s_admin.has_delete_permission(request))
