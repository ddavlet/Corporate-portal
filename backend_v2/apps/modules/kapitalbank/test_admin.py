import re
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.modules.kapitalbank.admin import BankAccountLinkForm
from apps.common.test_postgres_mcp_role import ROLE_SQL
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, gateway_ok
from apps.modules.kapitalbank.fixtures import ACCOUNT_1, ACCOUNT_2, CARD_REF, KapitalbankFixtures
from apps.modules.kapitalbank.models import (
    BankAccountLink,
    KapitalbankAlertSettings,
    KapitalbankConnection,
    SyncEvent,
)
from apps.modules.wallets.models import BankAccount
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account
from apps.tenants.models import Tenant

User = get_user_model()
SECRET = "Zx9-very-secret-pw"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class KapitalbankAdminTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.admin_user = User.objects.create_superuser(username="kb-root", password="x", full_name="Root")
        self.client = Client(HTTP_HOST="kp.example.com")
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
            "tenant": self.tenant.pk,
            "account_no": ACCOUNT_1,
            "branch": "01158",
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
        data = {
            **self._link_data(bank_account=self.bank_account1.pk),
            "sync_state-TOTAL_FORMS": "0",
            "sync_state-INITIAL_FORMS": "0",
            "sync_state-MIN_NUM_FORMS": "0",
            "sync_state-MAX_NUM_FORMS": "1",
        }
        resp = self.client.post(url, data)
        form = resp.context_data["adminform"].form if resp.status_code == 200 else None
        self.assertEqual(resp.status_code, 302, form.errors if form else "")
        link.refresh_from_db()
        self.assertEqual(link.decided_by, self.admin_user)
        first = link.decided_at
        self.assertIsNotNone(first)
        # unchanged resubmission keeps decided_at
        self.client.post(url, data)
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

        SyncEvent.objects.create(tenant=self.tenant, kind="imported", message="fresh-evt")
        old = SyncEvent.objects.create(tenant=self.tenant, kind="imported", message="stale-evt")
        SyncEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=60))
        url = reverse("admin:kapitalbank_syncevent_changelist")
        body = self.client.get(url).content.decode()
        self.assertIn("fresh-evt", body)
        self.assertNotIn("stale-evt", body)
        body_all = self.client.get(url, {"period": "all"}).content.decode()
        self.assertIn("stale-evt", body_all)

    def test_alert_settings_single_and_not_deletable(self):
        request = RequestFactory().get("/")
        request.user = self.admin_user
        s_admin = site._registry[KapitalbankAlertSettings]
        self.assertTrue(s_admin.has_add_permission(request))
        KapitalbankAlertSettings.load()
        self.assertFalse(s_admin.has_add_permission(request))
        self.assertFalse(s_admin.has_delete_permission(request))

    def test_login_not_in_connection_list_but_editable(self):
        c = self._conn()
        listing = self.client.get(reverse("admin:kapitalbank_kapitalbankconnection_changelist")).content.decode()
        self.assertNotIn("bank-user", listing)
        self.assertNotIn("login", site._registry[KapitalbankConnection].list_display)
        self.assertNotIn("login", site._registry[KapitalbankConnection].search_fields)
        change = self.client.get(reverse("admin:kapitalbank_kapitalbankconnection_change", args=[c.pk])).content.decode()
        self.assertIn('name="login"', change)
        self.assertIn("bank-user", change)

    @skipUnless(ROLE_SQL.exists(), "scripts/ is not available (backend_v2-only checkout)")
    def test_mcp_readonly_role_hides_bank_login_and_password(self):
        sql = ROLE_SQL.read_text()
        block = sql.split("INSERT INTO mcp_hidden_columns (tbl, col) VALUES", 1)[1].split(";", 1)[0]
        hidden = set(re.findall(r"\('([a-z0-9_]+)',\s*'([a-z0-9_]+)'\)", block))
        self.assertIn(("kapitalbank_kapitalbankconnection", "login"), hidden)
        self.assertIn(("kapitalbank_kapitalbankconnection", "password_enc"), hidden)

    def test_bank_link_must_match_account_and_mfo(self):
        link = self._link()  # ACCOUNT_1 / 01158
        form = BankAccountLinkForm(self._link_data(bank_account=self.bank_account2.pk), instance=link)
        self.assertFalse(form.is_valid())
        self.assertIn("не совпадает со счётом банка", form.errors["bank_account"][0])
        other_mfo = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no=ACCOUNT_1, mfo="00014")
        form = BankAccountLinkForm(self._link_data(bank_account=other_mfo.bank_account.pk), instance=link)
        self.assertFalse(form.is_valid())
        self.assertIn("МФО", form.errors["bank_account"][0])
        # add form: account_no/branch come from the submitted data
        add_form = BankAccountLinkForm(self._link_data(account_no=ACCOUNT_2, bank_account=self.bank_account1.pk))
        self.assertFalse(add_form.is_valid())
        self.assertIn("bank_account", add_form.errors)
        ok = BankAccountLinkForm(self._link_data(account_no=ACCOUNT_2, bank_account=self.bank_account2.pk))
        self.assertTrue(ok.is_valid(), ok.errors)

    def test_card_link_must_match_external_ref(self):
        link = self._link(account_no="22618000100000000999")
        form = BankAccountLinkForm(
            self._link_data(account_no="22618000100000000999", card_account=self.card_account.pk), instance=link
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Внешний номер карточного счёта", form.errors["card_account"][0])
        card_link = self._link(account_no=CARD_REF)
        form = BankAccountLinkForm(self._link_data(account_no=CARD_REF, card_account=self.card_account.pk), instance=card_link)
        self.assertTrue(form.is_valid(), form.errors)

    def test_change_form_with_readonly_account_still_checks_match(self):
        link = self._link()
        url = reverse("admin:kapitalbank_bankaccountlink_change", args=[link.pk])
        data = {
            **self._link_data(bank_account=self.bank_account2.pk),
            "sync_state-TOTAL_FORMS": "0",
            "sync_state-INITIAL_FORMS": "0",
            "sync_state-MIN_NUM_FORMS": "0",
            "sync_state-MAX_NUM_FORMS": "1",
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("bank_account", resp.context_data["adminform"].form.errors)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)

    def test_add_form_limits_accounts_to_known_tenant(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        foreign = get_or_create_bank_wallet_for_account(tenant=other, account_no="20208000111111111001", mfo="01158")
        bound = BankAccountLinkForm(self._link_data())
        unbound = BankAccountLinkForm(initial={"tenant": str(self.tenant.pk)})
        for form in (bound, unbound):
            banks = set(form.fields["bank_account"].queryset.values_list("pk", flat=True))
            self.assertIn(self.bank_account1.pk, banks)
            self.assertNotIn(foreign.bank_account.pk, banks)
            self.assertTrue(
                set(form.fields["card_account"].queryset.values_list("tenant_id", flat=True)) <= {self.tenant.pk}
            )

    def test_event_list_selects_tenant_and_link(self):
        self.assertEqual(site._registry[SyncEvent].list_select_related, ("tenant", "link"))

    def _ignore_post(self, links, **extra):
        url = reverse("admin:kapitalbank_bankaccountlink_changelist")
        data = {"action": "ignore_selected", "index": "0", "_selected_action": [str(link.pk) for link in links]}
        data.update(extra)
        return self.client.post(url, data)

    def test_bulk_ignore_asks_for_reason_first(self):
        link = self._link(account_no="16401000504843803001")
        resp = self._ignore_post([link])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "16401000504843803001")
        self.assertContains(resp, 'name="ignore_reason"')
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)

    def test_bulk_ignore_sets_reason_only_on_pending(self):
        pending = [self._link(account_no="16401000504843803001"), self._link(account_no="23510000104843803001")]
        linked = self._link(decision=BankAccountLink.LINKED, bank_account=self.bank_account1)
        old = self._link(account_no="22613000204843803001", decision=BankAccountLink.IGNORED, ignore_reason="старая")
        resp = self._ignore_post(pending + [linked, old], apply="1", ignore_reason="  Служебный счёт банка  ")
        self.assertEqual(resp.status_code, 302)
        for link in pending:
            link.refresh_from_db()
            self.assertEqual(link.decision, BankAccountLink.IGNORED)
            self.assertEqual(link.ignore_reason, "Служебный счёт банка")
            self.assertEqual(link.decided_by, self.admin_user)
            self.assertIsNotNone(link.decided_at)
        linked.refresh_from_db()
        self.assertEqual(linked.decision, BankAccountLink.LINKED)
        self.assertEqual(linked.bank_account, self.bank_account1)
        old.refresh_from_db()
        self.assertEqual(old.ignore_reason, "старая")
        self.assertIsNone(old.decided_by)

    def test_bulk_ignore_requires_reason(self):
        link = self._link(account_no="16401000504843803001")
        resp = self._ignore_post([link], apply="1", ignore_reason="   ")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context_data["form"].errors)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.PENDING)
        self.assertEqual(link.ignore_reason, "")

    def test_bulk_ignore_without_pending_changes_nothing(self):
        linked = self._link(decision=BankAccountLink.LINKED, bank_account=self.bank_account1)
        resp = self._ignore_post([linked])
        self.assertEqual(resp.status_code, 302)
        linked.refresh_from_db()
        self.assertEqual(linked.decision, BankAccountLink.LINKED)

    @patch(GATEWAY_PATH)
    def test_admin_type_change_on_linked_bank_link_alerts(self, gw):
        gw.side_effect = gateway_ok()
        settings_obj = KapitalbankAlertSettings.load()
        settings_obj.recipient = self.owner
        settings_obj.save()
        decided_at = timezone.now() - timedelta(days=3)
        link = self._link(
            decision=BankAccountLink.LINKED, bank_account=self.bank_account1, decided_by=self.owner, decided_at=decided_at
        )
        pending = self._link(account_no=ACCOUNT_2)
        url = reverse("admin:kapitalbank_bankaccountlink_change", args=[link.pk])
        self.assertContains(self.client.get(url), 'name="account_type"')
        pending_page = self.client.get(reverse("admin:kapitalbank_bankaccountlink_change", args=[pending.pk]))
        self.assertNotContains(pending_page, 'name="account_type"')

        data = {
            **self._link_data(bank_account=self.bank_account1.pk, account_type=BankAccount.AccountType.INFORMATIONAL),
            "sync_state-TOTAL_FORMS": "0",
            "sync_state-INITIAL_FORMS": "0",
            "sync_state-MIN_NUM_FORMS": "0",
            "sync_state-MAX_NUM_FORMS": "1",
        }
        resp = self.client.post(url, data)
        form = resp.context_data["adminform"].form if resp.status_code == 200 else None
        self.assertEqual(resp.status_code, 302, form.errors if form else "")

        self.bank_account1.refresh_from_db()
        self.assertEqual(self.bank_account1.account_type, BankAccount.AccountType.INFORMATIONAL)
        link.refresh_from_db()
        self.assertEqual(link.decision, BankAccountLink.LINKED)
        self.assertEqual(link.decided_by, self.owner)
        self.assertEqual(link.decided_at, decided_at)
        event = SyncEvent.objects.get(kind=SyncEvent.ALERT_TYPE_CHANGED)
        self.assertEqual(event.link, link)
        self.assertEqual(event.payload["changed_by"], self.admin_user.pk)
        self.assertIn("Root", event.message)
        self.assertEqual(gw.call_count, 1)

        # resubmitting the same type changes nothing and sends nothing
        self.client.post(url, data)
        self.assertEqual(SyncEvent.objects.filter(kind=SyncEvent.ALERT_TYPE_CHANGED).count(), 1)
        self.assertEqual(gw.call_count, 1)
