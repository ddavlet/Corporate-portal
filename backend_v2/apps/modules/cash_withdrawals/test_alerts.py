import datetime as dt
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.modules.cash_withdrawals.alerts import process_due_alerts
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, CashWithdrawalFixtures, gateway_ok
from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt

TZ = ZoneInfo("Asia/Tashkent")


def tashkent(y, m, d, h, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=TZ)


@override_settings(BASE_DOMAIN="example.com")
class AlertTests(CashWithdrawalFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        # created 25.09 23:30 Tashkent; day counting uses Tashkent dates (see boundary test below)
        self.receipt = self.make_receipt(created_at=tashkent(2026, 9, 25, 23, 30))

    @patch(GATEWAY_PATH)
    def test_no_alert_before_n_days(self, gw):
        gw.side_effect = gateway_ok()
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 27, 9)), 0)
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_alert_on_day_n_at_alert_hour_only(self, gw):
        gw.side_effect = gateway_ok()
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 28, 8)), 0)
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 28, 9)), 1)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.alert_count, 1)
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "91000")
        self.assertIn("— 3 дн.", payload["text"])
        self.assertEqual(payload["buttons"], [])

    @patch(GATEWAY_PATH)
    def test_no_duplicate_same_day_and_repeat_after_m_days(self, gw):
        gw.side_effect = gateway_ok()
        self.config.alert_repeat_every_days = 2
        self.config.save(update_fields=["alert_repeat_every_days"])
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 28, 9)), 1)
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 28, 9, 30)), 0)
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 29, 9)), 0)
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 30, 9)), 1)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.alert_count, 2)

    @patch(GATEWAY_PATH)
    def test_confirmed_or_closed_receipts_are_silent(self, gw):
        gw.side_effect = gateway_ok()
        CashWithdrawalReceipt.objects.filter(pk=self.receipt.pk).update(status=CashWithdrawalReceipt.Status.CLOSED)
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 28, 9)), 0)

    @patch(GATEWAY_PATH)
    def test_disabled_config_is_silent(self, gw):
        gw.side_effect = gateway_ok()
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 28, 9)), 0)

    @patch(GATEWAY_PATH)
    def test_days_counted_by_tashkent_dates(self, gw):
        gw.side_effect = gateway_ok()
        # 26.09 00:30 Tashkent == 25.09 19:30 UTC — must count from 26.09
        late = self.make_receipt(created_at=tashkent(2026, 9, 26, 0, 30))
        process_due_alerts(now_dt=tashkent(2026, 9, 28, 9))
        late.refresh_from_db()
        self.assertEqual(late.alert_count, 0)  # only 2 days by local dates
        process_due_alerts(now_dt=tashkent(2026, 9, 29, 9))
        late.refresh_from_db()
        self.assertEqual(late.alert_count, 1)

    @patch(GATEWAY_PATH, return_value=None)
    def test_undelivered_alert_does_not_count(self, gw):
        self.assertEqual(process_due_alerts(now_dt=tashkent(2026, 9, 28, 9)), 0)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.alert_count, 0)
        self.assertIsNone(self.receipt.last_alert_at)

    @patch(GATEWAY_PATH)
    def test_management_command(self, gw):
        gw.side_effect = gateway_ok()
        out = StringIO()
        call_command("run_cash_withdrawal_alerts", "--now=2026-09-28T09:00:00+05:00", stdout=out)
        self.assertIn("Cash withdrawal alerts dispatched: 1", out.getvalue())
