from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, gateway_ok

from .alerts import format_amount, notify_down, notify_missing_docs, notify_mismatch, notify_own_transfer, notify_resolved, send_owner_alert
from .client import StatementDoc
from .fixtures import ACCOUNT_1, ACCOUNT_2, MFO, KapitalbankFixtures
from .models import AccountSyncState, BankAccountLink, KapitalbankAlertSettings, KapitalbankConnection, SyncEvent

PASSWORD = "S3cret-bank-pass"


def utc(day, hour, minute):
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


class AlertsTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        conn = KapitalbankConnection(tenant=self.tenant, login="IB#secretlogin", is_enabled=True)
        conn.set_password(PASSWORD)
        conn.save()
        settings_obj = KapitalbankAlertSettings.load()
        settings_obj.bot_tenant = self.tenant
        settings_obj.recipient = self.owner
        settings_obj.save()
        self.link = BankAccountLink.objects.create(
            tenant=self.tenant, account_no=ACCOUNT_1, branch=MFO, name="Расчетный счет 1",
            decision=BankAccountLink.LINKED, bank_account=self.bank_account1,
        )

    def doc(self):
        return StatementDoc(
            general_id="GEN1", b2_id="B1", num="1", ddate=date(2026, 10, 20), vdate=date(2026, 10, 20),
            acc_dt=ACCOUNT_1, acc_ct=ACCOUNT_2, name_dt="A", name_ct="B", inn_dt="1", inn_ct="2",
            mfo_dt=MFO, mfo_ct=MFO, purpose="Перевод <между> своими", dtype="21",
            amount=Decimal("1500000.50"), state=1, dir=2,
        )

    def test_format_amount(self):
        self.assertEqual(format_amount(Decimal("-361569643.41")), "-361 569 643,41")
        self.assertEqual(format_amount(Decimal("5")), "5,00")

    @patch(GATEWAY_PATH)
    def test_mismatch_sent_once_then_daily(self, gw):
        gw.side_effect = gateway_ok()
        kw = dict(bank=Decimal("1000.00"), portal=Decimal("-361568643.41"))
        self.assertTrue(notify_mismatch(self.link, now=utc(1, 10, 0), **kw))
        self.assertFalse(notify_mismatch(self.link, now=utc(1, 10, 10), **kw))
        self.assertTrue(notify_mismatch(self.link, now=utc(2, 10, 20), **kw))
        self.assertEqual(gw.call_count, 2)
        payload = gw.call_args_list[0].kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "1387986")
        self.assertIn("-361 569 643,41", payload["text"])
        self.assertIn("Kolberg Plus", payload["text"])
        self.assertIn("…3001", payload["text"])

    @patch(GATEWAY_PATH)
    def test_resolved_sent_once_after_mismatch(self, gw):
        gw.side_effect = gateway_ok()
        self.assertFalse(notify_resolved(self.link, now=utc(1, 9, 0)))
        notify_mismatch(self.link, bank=Decimal("1"), portal=Decimal("2"), now=utc(1, 10, 0))
        self.assertTrue(notify_resolved(self.link, now=utc(1, 11, 0)))
        self.assertFalse(notify_resolved(self.link, now=utc(1, 12, 0)))
        self.assertEqual(gw.call_count, 2)
        state = AccountSyncState.objects.get(link=self.link)
        self.assertIsNone(state.mismatch_since)
        self.assertIsNone(state.mismatch_alerted_at)

    @patch(GATEWAY_PATH)
    def test_down_alert_at_most_daily(self, gw):
        gw.side_effect = gateway_ok()
        self.assertTrue(notify_down(self.link, code=401, message="Неверный <пароль>", now=utc(1, 10, 0)))
        self.assertFalse(notify_down(self.link, code=401, message="x", now=utc(1, 20, 0)))
        self.assertTrue(notify_down(self.link, code=None, message="x", now=utc(2, 10, 1)))
        self.assertIn("&lt;пароль&gt;", gw.call_args_list[0].kwargs["payload"]["text"])

    @patch(GATEWAY_PATH)
    def test_own_transfer_once_per_document(self, gw):
        gw.side_effect = gateway_ok()
        self.assertTrue(notify_own_transfer(self.link, self.doc(), target_account=ACCOUNT_2))
        self.assertFalse(notify_own_transfer(self.link, self.doc(), target_account=ACCOUNT_2))
        self.assertEqual(gw.call_count, 1)
        text = gw.call_args.kwargs["payload"]["text"]
        self.assertIn("1 500 000,50", text)
        self.assertIn("счёт не отслеживается", text)
        self.assertIn("&lt;между&gt;", text)
        self.assertTrue(SyncEvent.objects.filter(dedup_key=f"own_transfer:{self.link.pk}:GEN1").exists())

    @patch(GATEWAY_PATH)
    def test_own_transfer_pending_target_says_not_decided(self, gw):
        gw.side_effect = gateway_ok()
        BankAccountLink.objects.create(tenant=self.tenant, account_no=ACCOUNT_2, branch=MFO)
        notify_own_transfer(self.link, self.doc(), target_account=ACCOUNT_2)
        self.assertIn("счёт не разобран", gw.call_args.kwargs["payload"]["text"])

    @patch(GATEWAY_PATH)
    def test_missing_docs_once_per_day(self, gw):
        gw.side_effect = gateway_ok()
        day = date(2026, 10, 20)
        self.assertTrue(notify_missing_docs(self.link, day=day, external_ids=["A", "B"], now=utc(21, 8, 0)))
        self.assertFalse(notify_missing_docs(self.link, day=day, external_ids=["A", "B"], now=utc(21, 9, 0)))
        self.assertTrue(notify_missing_docs(self.link, day=day, external_ids=["A", "B"], now=utc(22, 8, 0)))
        self.assertEqual(gw.call_count, 2)

    @patch(GATEWAY_PATH)
    def test_failed_send_does_not_block_retry(self, gw):
        gw.return_value = None
        args = dict(tenant=self.tenant, link=self.link, kind=SyncEvent.ALERT_OWN_TRANSFER, dedup_key="k1")
        self.assertFalse(send_owner_alert("t", **args))
        gw.side_effect = gateway_ok()
        self.assertTrue(send_owner_alert("t", **args))
        self.assertFalse(send_owner_alert("t", **args))
        self.assertEqual(SyncEvent.objects.filter(dedup_key="k1").count(), 1)

    @patch(GATEWAY_PATH)
    def test_mismatch_not_marked_alerted_when_send_fails(self, gw):
        gw.return_value = None
        kw = dict(bank=Decimal("1"), portal=Decimal("2"))
        self.assertFalse(notify_mismatch(self.link, now=utc(1, 10, 0), **kw))
        self.assertIsNone(AccountSyncState.objects.get(link=self.link).mismatch_alerted_at)
        gw.return_value = {"message_id": 1}
        self.assertTrue(notify_mismatch(self.link, now=utc(1, 10, 5), **kw))

    @patch(GATEWAY_PATH)
    def test_no_settings_logs_and_returns_false(self, gw):
        KapitalbankAlertSettings.objects.filter(pk=1).update(bot_tenant=None)
        with self.assertLogs("apps.modules.kapitalbank.alerts", level="ERROR"):
            self.assertFalse(notify_down(self.link, code=1, message="m", now=utc(1, 10, 0)))
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_no_password_in_alert_text(self, gw):
        gw.side_effect = gateway_ok()
        notify_mismatch(self.link, bank=Decimal("1"), portal=Decimal("2"), now=utc(1, 10, 0))
        notify_resolved(self.link, now=utc(1, 11, 0))
        notify_down(self.link, code=500, message="err", now=utc(1, 12, 0))
        notify_own_transfer(self.link, self.doc(), target_account=ACCOUNT_2)
        notify_missing_docs(self.link, day=date(2026, 10, 20), external_ids=["A"], now=utc(1, 13, 0))
        texts = [c.kwargs["payload"]["text"] for c in gw.call_args_list]
        texts += list(SyncEvent.objects.values_list("message", flat=True))
        self.assertEqual(len(gw.call_args_list), 5)
        for text in texts:
            self.assertNotIn(PASSWORD, text)
            self.assertNotIn("secretlogin", text)
        for payload in SyncEvent.objects.values_list("payload", flat=True):
            self.assertNotIn(PASSWORD, str(payload))
