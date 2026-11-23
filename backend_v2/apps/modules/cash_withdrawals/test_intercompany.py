"""Intercompany receipts: a group company's PAYED request awaits cash in another tenant (the УК)."""

import datetime as dt
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings

from apps.modules.cash_withdrawals import formatter
from apps.modules.cash_withdrawals.alerts import process_due_alerts
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, CashWithdrawalFixtures, gateway_ok
from apps.modules.cash_withdrawals.models import CashWithdrawalMessage, CashWithdrawalReceipt
from apps.modules.cash_withdrawals.services import (
    IntercompanyReceiptError,
    confirm_receipt,
    create_intercompany_receipt,
)
from apps.modules.cashier.models import CashRevenue
from apps.modules.requests.models import Request
from apps.modules.wallets.models import CashRegister, Wallet
from apps.modules.wallets.resolution import get_or_create_bank_wallet, get_or_create_cash_wallet
from apps.tenants.models import Tenant

TZ = ZoneInfo("Asia/Tashkent")
REGISTRY_PATH = "apps.modules.cash_withdrawals.events.RECEIPT_CONFIRMED_HANDLERS"
HANDOVER_PURPOSE = "Передача в УК"


class IntercompanyFixtures(CashWithdrawalFixtures):
    """self.tenant (from CashWithdrawalFixtures) is the receiving УК; self.sender is a group company."""

    def make_intercompany_fixtures(self) -> None:
        self.make_fixtures()
        self.sender = Tenant.objects.create(name="Lemonfit ONE", subdomain="lemonone", is_active=True)

    def make_sender_request(self, **overrides) -> Request:
        data = {
            "tenant": self.sender,
            "payment_purpose": HANDOVER_PURPOSE,
            "amount": Decimal("25000000.00"),
            "description": "Выручка за неделю",
        }
        data.update(overrides)
        return self.make_request(**data)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="")
class CreateIntercompanyReceiptTests(IntercompanyFixtures, TestCase):
    def setUp(self):
        self.make_intercompany_fixtures()

    def _create(self, request_obj=None, wallet=None, tenant=None):
        return create_intercompany_receipt(
            tenant=tenant or self.tenant,
            request_id=(request_obj or self.make_sender_request()).pk,
            wallet_id=(wallet or self.wallet).pk,
        )

    def _assert_refused(self, code, **kwargs):
        with self.assertRaises(IntercompanyReceiptError) as ctx:
            self._create(**kwargs)
        self.assertEqual(ctx.exception.code, code)
        self.assertFalse(CashWithdrawalReceipt.objects.exists())
        return ctx.exception

    @patch(GATEWAY_PATH)
    def test_creates_receipt_in_receiving_tenant_and_sends_card(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_sender_request()
        with self.captureOnCommitCallbacks(execute=True):
            receipt, created = self._create(request_obj=req)
        self.assertTrue(created)
        self.assertEqual(receipt.tenant_id, self.tenant.id)
        self.assertEqual(receipt.wallet_id, self.wallet.id)
        self.assertEqual(receipt.request_id, req.id)
        self.assertEqual(receipt.amount, Decimal("25000000.00"))
        self.assertEqual(receipt.currency, "UZS")
        self.assertEqual(receipt.status, CashWithdrawalReceipt.Status.PENDING)
        self.assertEqual(gw.call_count, 1)
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "-100500")  # card group of the receiving tenant
        self.assertEqual(payload["tenant_id"], str(self.tenant.id))
        self.assertIn("От компании: Lemonfit ONE", payload["text"])
        self.assertEqual(receipt.messages.filter(kind=CashWithdrawalMessage.Kind.CARD).count(), 1)

    @patch(GATEWAY_PATH)
    def test_repeat_call_returns_existing_without_second_card(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_sender_request()
        with self.captureOnCommitCallbacks(execute=True):
            first, _ = self._create(request_obj=req)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            again, created = self._create(request_obj=req)
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(callbacks, [])
        self.assertEqual(CashWithdrawalReceipt.objects.filter(request=req).count(), 1)
        self.assertEqual(gw.call_count, 1)

    @patch(GATEWAY_PATH)
    def test_existing_receipt_with_other_wallet_is_conflict(self, gw):
        gw.side_effect = gateway_ok()
        req = self.make_sender_request()
        with self.captureOnCommitCallbacks(execute=True):
            first, _ = self._create(request_obj=req)
        safe = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Сейф")
        other_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=safe
        )
        with self.assertRaises(IntercompanyReceiptError) as ctx:
            self._create(request_obj=req, wallet=other_wallet)
        self.assertEqual(ctx.exception.code, IntercompanyReceiptError.CONFLICT)
        first.refresh_from_db()
        self.assertEqual(first.wallet_id, self.wallet.id)

    def test_existing_receipt_in_sender_tenant_is_conflict(self):
        req = self.make_sender_request()
        sender_wallet = get_or_create_cash_wallet(tenant=self.sender, currency="UZS")
        CashWithdrawalReceipt.objects.create(
            tenant=self.sender, request=req, wallet=sender_wallet, amount=req.amount, currency=req.currency
        )
        with self.assertRaises(IntercompanyReceiptError) as ctx:
            self._create(request_obj=req)
        self.assertEqual(ctx.exception.code, IntercompanyReceiptError.CONFLICT)
        self.assertEqual(CashWithdrawalReceipt.objects.get().tenant_id, self.sender.id)

    def test_not_payed_request_is_refused(self):
        err = self._assert_refused(
            "request_not_payed", request_obj=self.make_sender_request(status=Request.STATUS_APPROVED)
        )
        self.assertEqual(err.field, "request_id")

    def test_deleted_request_is_refused(self):
        self._assert_refused("request_not_payed", request_obj=self.make_sender_request(status=Request.STATUS_DELETED))

    def test_missing_request_is_refused(self):
        with self.assertRaises(IntercompanyReceiptError) as ctx:
            create_intercompany_receipt(tenant=self.tenant, request_id=987654321, wallet_id=self.wallet.pk)
        self.assertEqual(ctx.exception.code, "request_not_found")

    def test_same_tenant_request_is_refused(self):
        self._assert_refused("same_tenant", request_obj=self.make_request(payment_purpose=HANDOVER_PURPOSE))

    def test_wallet_of_other_tenant_is_refused(self):
        err = self._assert_refused("wallet_invalid", wallet=get_or_create_cash_wallet(tenant=self.sender, currency="UZS"))
        self.assertEqual(err.field, "wallet_id")

    def test_non_cash_wallet_is_refused(self):
        self._assert_refused("wallet_invalid", wallet=get_or_create_bank_wallet(tenant=self.tenant))

    def test_currency_mismatch_is_refused(self):
        self._assert_refused("currency_mismatch", request_obj=self.make_sender_request(currency="USD"))

    def test_request_of_inactive_sender_is_not_found(self):
        req = self.make_sender_request()
        self.sender.is_active = False
        self.sender.save(update_fields=["is_active"])
        self._assert_refused("request_not_found", request_obj=req)

    def test_missing_tenant_is_refused(self):
        with self.assertRaises(IntercompanyReceiptError) as ctx:
            create_intercompany_receipt(tenant=None, request_id=1, wallet_id=self.wallet.pk)
        self.assertEqual(ctx.exception.code, "config_inactive")

    def test_inactive_config_is_refused(self):
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        self._assert_refused("config_inactive")


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="")
class IntercompanyReceiptLifecycleTests(IntercompanyFixtures, TestCase):
    def setUp(self):
        self.make_intercompany_fixtures()
        patcher = patch(REGISTRY_PATH, ())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.request_obj = self.make_sender_request()
        self.receipt = self.make_receipt(self.request_obj)

    @patch(GATEWAY_PATH)
    def test_confirm_creates_revenue_in_receiving_tenant(self, gw):
        gw.side_effect = gateway_ok()
        with self.captureOnCommitCallbacks(execute=True):
            receipt, created = confirm_receipt(receipt_id=self.receipt.pk, user=self.cashier)
        self.assertTrue(created)
        revenue = CashRevenue.objects.get(pk=receipt.cash_revenue_id)
        self.assertEqual(revenue.tenant_id, self.tenant.id)
        self.assertEqual(revenue.wallet_id, self.wallet.id)
        self.assertEqual(revenue.total_sum, Decimal("25000000.00"))
        self.assertEqual(revenue.external_id, f"cash-{self.request_obj.pk}")
        self.assertEqual(revenue.operation, "Наличные от Lemonfit ONE")
        self.assertEqual(revenue.counterparty, "Lemonfit ONE")
        self.assertIn(f"Заявка №{self.request_obj.pk}", revenue.comment)
        self.assertIn("Выручка за неделю", revenue.comment)
        self.assertEqual(revenue.payload["from_tenant_id"], self.sender.id)
        self.assertFalse(CashRevenue.objects.filter(tenant=self.sender).exists())

    def test_operation_label_is_constant_per_sender(self):
        """P&L groups incomes by exact `operation`: no request number in the label."""
        other = self.make_receipt(self.make_sender_request(description=""))
        first, _ = confirm_receipt(receipt_id=self.receipt.pk, user=self.cashier)
        second, _ = confirm_receipt(receipt_id=other.pk, user=self.cashier)
        labels = set(CashRevenue.objects.filter(tenant=self.tenant).values_list("operation", flat=True))
        self.assertEqual(labels, {"Наличные от Lemonfit ONE"})
        self.assertNotEqual(first.cash_revenue_id, second.cash_revenue_id)

    def test_confirm_links_existing_revenue_instead_of_duplicate(self):
        now = dt.datetime.now(TZ)
        existing = CashRevenue.objects.create(
            tenant=self.tenant,
            wallet=self.wallet,
            total_sum=Decimal("25000000.00"),
            currency="UZS",
            revenue_at=now,
            external_id=f"cash-{self.request_obj.pk}",
            source_year=now.year,
            created_by=self.cashier,
        )
        receipt, created = confirm_receipt(receipt_id=self.receipt.pk, user=self.cashier)
        self.assertTrue(created)
        self.assertEqual(receipt.cash_revenue_id, existing.pk)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(receipt.status, CashWithdrawalReceipt.Status.CONFIRMED)

    def test_confirm_does_not_collide_with_receiving_tenant_own_withdrawal(self):
        own = self.make_receipt(self.make_request())
        confirm_receipt(receipt_id=own.pk, user=self.cashier)
        confirm_receipt(receipt_id=self.receipt.pk, user=self.cashier)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 2)

    def test_card_and_alert_texts_show_sender_company(self):
        card = formatter.build_card_text(receipt=self.receipt, confirmers=[self.cashier])
        self.assertIn("От компании: Lemonfit ONE", card)
        self.assertIn(f"https://lemonone.example.com/app/requests/{self.request_obj.pk}", card)
        alert = formatter.build_alert_text(receipt=self.receipt, days=3, responsible=[self.cashier])
        self.assertIn("От компании: Lemonfit ONE", alert)

    def test_same_tenant_texts_have_no_sender_line(self):
        receipt = self.make_receipt()
        self.assertNotIn("От компании", formatter.build_card_text(receipt=receipt, confirmers=[]))
        self.assertNotIn("От компании", formatter.build_alert_text(receipt=receipt, days=3, responsible=[]))

    @patch(GATEWAY_PATH)
    def test_overdue_alert_picks_up_intercompany_receipt(self, gw):
        gw.side_effect = gateway_ok()
        CashWithdrawalReceipt.objects.filter(pk=self.receipt.pk).update(
            created_at=dt.datetime(2026, 9, 25, 12, 0, tzinfo=TZ)
        )
        self.assertEqual(process_due_alerts(now_dt=dt.datetime(2026, 9, 28, 9, 0, tzinfo=TZ)), 1)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.alert_count, 1)
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "91000")  # alert recipient of the receiving tenant
        self.assertIn("От компании: Lemonfit ONE", payload["text"])
