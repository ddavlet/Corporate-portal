from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import site
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings

from apps.modules.cash_withdrawals.admin import CashWithdrawalReceiptAdmin
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, CashWithdrawalFixtures, gateway_ok
from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt
from apps.modules.cash_withdrawals.services import close_receipt
from apps.modules.cashier.models import CashRevenue
from apps.modules.requests.models import RequestComment


@override_settings(BASE_DOMAIN="example.com")
class CloseReceiptTests(CashWithdrawalFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    @patch(GATEWAY_PATH)
    def test_close_sets_status_and_system_comment(self, gw):
        gw.side_effect = gateway_ok()
        receipt = self.make_receipt()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(close_receipt(receipt_id=receipt.pk, actor=self.admin, comment="ошибочное снятие"))
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, CashWithdrawalReceipt.Status.CLOSED)
        self.assertEqual(receipt.closed_by_id, self.admin.id)
        comment = RequestComment.objects.get(request=receipt.request)
        self.assertEqual(comment.created_by_id, 1)
        self.assertIn("ошибочное снятие", comment.body)

    def test_close_non_pending_is_noop(self):
        receipt = self.make_receipt(status=CashWithdrawalReceipt.Status.CONFIRMED)
        self.assertFalse(close_receipt(receipt_id=receipt.pk, actor=self.admin, comment="x"))
        self.assertFalse(RequestComment.objects.exists())

    @patch(GATEWAY_PATH)
    def test_admin_action_skips_receipts_without_comment(self, gw):
        gw.side_effect = gateway_ok()
        with_comment = self.make_receipt(closed_comment="деньги не пришли")
        without_comment = self.make_receipt()
        admin_obj = CashWithdrawalReceiptAdmin(CashWithdrawalReceipt, site)
        request = RequestFactory().post("/")
        request.user = self.admin
        admin_obj.message_user = lambda *a, **k: None
        with self.captureOnCommitCallbacks(execute=True):
            admin_obj.close_without_revenue(request, CashWithdrawalReceipt.objects.all())
        with_comment.refresh_from_db()
        without_comment.refresh_from_db()
        self.assertEqual(with_comment.status, CashWithdrawalReceipt.Status.CLOSED)
        self.assertEqual(without_comment.status, CashWithdrawalReceipt.Status.PENDING)


@override_settings(BASE_DOMAIN="example.com")
class BackfillTests(CashWithdrawalFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.lost = self.make_request(payed_at=20260910)
        self.old = self.make_request(payed_at=20260801)
        self.had_n8n_revenue = self.make_request(payed_at=20260915)
        CashRevenue.objects.create(
            tenant=self.tenant, wallet=self.wallet, total_sum=1, currency="UZS",
            external_id=f"cash-{self.had_n8n_revenue.pk}", created_by=self.admin,
        )
        self.other_purpose = self.make_request(payed_at=20260912, payment_purpose="Аренда")

    @patch(GATEWAY_PATH)
    def test_dry_run_creates_nothing(self, gw):
        out = StringIO()
        call_command("backfill_cash_withdrawal_receipts", "--tenant=lemonaqua", "--since=2026-09-01", stdout=out)
        self.assertFalse(CashWithdrawalReceipt.objects.exists())
        self.assertIn(f"#{self.lost.pk}", out.getvalue())
        self.assertNotIn(f"#{self.had_n8n_revenue.pk}", out.getvalue())
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_apply_creates_only_missing(self, gw):
        gw.side_effect = gateway_ok()
        with self.captureOnCommitCallbacks(execute=True):
            call_command(
                "backfill_cash_withdrawal_receipts", "--tenant=lemonaqua", "--since=2026-09-01", "--apply",
                stdout=StringIO(),
            )
        self.assertEqual(
            list(CashWithdrawalReceipt.objects.values_list("request_id", flat=True)), [self.lost.pk]
        )
        self.assertEqual(gw.call_count, 1)

    @patch(GATEWAY_PATH)
    def test_apply_no_send(self, gw):
        call_command(
            "backfill_cash_withdrawal_receipts", "--tenant=lemonaqua", "--since=2026-09-01", "--apply", "--no-send",
            stdout=StringIO(),
        )
        self.assertEqual(CashWithdrawalReceipt.objects.count(), 1)
        gw.assert_not_called()
