from decimal import Decimal

from django.test import TestCase

from apps.modules.cash_desk.fixtures import CashDeskFixtures
from apps.modules.cash_desk.models import CashRegisterTransferTarget
from apps.modules.cash_desk.transfer_revenue import (
    STALE_TARGET_ERROR,
    TransferDestinationError,
    ensure_transfer_revenue,
    resolve_transfer_destination,
)
from apps.modules.cashier.models import CashRevenue
from apps.modules.requests.models import Request
from apps.modules.wallets.models import CashRegister, Wallet


class TransferRevenueTests(CashDeskFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _transfer(self, line, **kw):
        return self.make_request(
            payment_purpose="Перевод между кассами", description=f"Комментарий\n{line}", **kw
        )

    def test_target_used(self):
        req = self.make_request(wallet_ref=self.main)
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant, request=req, to_wallet=self.safe, to_amount=Decimal("1500000.00")
        )
        dest = resolve_transfer_destination(req)
        self.assertEqual(dest.wallet, self.safe)
        self.assertEqual(dest.amount, Decimal("1500000.00"))
        self.assertEqual(dest.currency, "UZS")

    def test_cross_currency_target_amount_and_currency(self):
        req = self.make_request(wallet_ref=self.main)
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.usd,
            to_amount=Decimal("120.50"),
            source_amount=req.amount,
            source_currency=req.currency,
        )
        dest = resolve_transfer_destination(req)
        self.assertEqual(dest.wallet, self.usd)
        self.assertEqual(dest.amount, Decimal("120.50"))
        self.assertEqual(dest.currency, "USD")

    def test_same_currency_target_uses_current_request_amount(self):
        req = self.make_request(wallet_ref=self.main)
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.safe,
            to_amount=req.amount,
            source_amount=req.amount,
            source_currency=req.currency,
        )
        Request.objects.filter(pk=req.pk).update(amount=Decimal("2000000.00"))
        req.refresh_from_db()
        dest = resolve_transfer_destination(req)
        self.assertEqual(dest.wallet, self.safe)
        self.assertEqual(dest.amount, Decimal("2000000.00"))
        self.assertEqual(dest.currency, "UZS")

    def test_cross_currency_target_amount_changed_raises(self):
        req = self.make_request(wallet_ref=self.main)
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.usd,
            to_amount=Decimal("120.50"),
            source_amount=req.amount,
            source_currency=req.currency,
        )
        Request.objects.filter(pk=req.pk).update(amount=Decimal("2000000.00"))
        req.refresh_from_db()
        with self.assertRaisesMessage(TransferDestinationError, STALE_TARGET_ERROR):
            resolve_transfer_destination(req)

    def test_cross_currency_target_currency_changed_raises(self):
        req = self.make_request(wallet_ref=self.main)
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant,
            request=req,
            to_wallet=self.usd,
            to_amount=Decimal("120.50"),
            source_amount=req.amount,
            source_currency="EUR",
        )
        with self.assertRaisesMessage(TransferDestinationError, STALE_TARGET_ERROR):
            resolve_transfer_destination(req)

    def test_cross_currency_target_without_snapshot_raises(self):
        req = self.make_request(wallet_ref=self.main)
        CashRegisterTransferTarget.objects.create(
            tenant=self.tenant, request=req, to_wallet=self.usd, to_amount=Decimal("120.50")
        )
        with self.assertRaisesMessage(TransferDestinationError, STALE_TARGET_ERROR):
            resolve_transfer_destination(req)

    def test_fallback_by_description_with_currency_suffix(self):
        req = self._transfer("В кассу: Сейф (UZS)")
        dest = resolve_transfer_destination(req)
        self.assertEqual(dest.wallet, self.safe)
        self.assertEqual(dest.amount, req.amount)
        self.assertEqual(dest.currency, "UZS")

    def test_fallback_ignores_case_and_spaces(self):
        req = self._transfer("В кассу:   сЕйФ  ")
        self.assertEqual(resolve_transfer_destination(req).wallet, self.safe)

    def test_fallback_matches_register_with_kassa_suffix(self):
        req = self._transfer("В кассу: Основная касса")
        self.assertEqual(resolve_transfer_destination(req).wallet, self.main)

    def test_fallback_unknown_register_raises(self):
        req = self._transfer("В кассу: Несуществующая")
        with self.assertRaisesMessage(TransferDestinationError, "Не найдена касса-получатель «Несуществующая»"):
            resolve_transfer_destination(req)

    def test_fallback_no_line_raises(self):
        req = self.make_request(description="Без строки")
        with self.assertRaisesMessage(TransferDestinationError, "В описании нет строки «В кассу: …»"):
            resolve_transfer_destination(req)

    def test_fallback_ambiguous_raises(self):
        register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="сейф", is_active=False)
        Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", opening_balance=0, cash_register=register
        )
        req = self._transfer("В кассу: Сейф")
        with self.assertRaisesMessage(TransferDestinationError, "Найдено несколько касс «Сейф»"):
            resolve_transfer_destination(req)

    def test_fallback_currency_mismatch_raises(self):
        req = self._transfer("В кассу: Касса USD")
        with self.assertRaisesMessage(TransferDestinationError, "Валюта кассы «Касса USD» (USD) не совпадает"):
            resolve_transfer_destination(req)

    def test_existing_n8n_revenue_not_duplicated(self):
        req = self._transfer("В кассу: Сейф")
        existing = CashRevenue.objects.create(
            tenant=self.tenant,
            wallet=self.safe,
            total_sum=req.amount,
            currency="UZS",
            external_id=f"cash-{req.pk}",
            source_year=2025,
            created_by=self.admin,
        )
        dest = resolve_transfer_destination(req)
        revenue, created = ensure_transfer_revenue(request_obj=req, destination=dest)
        self.assertFalse(created)
        self.assertEqual(revenue.pk, existing.pk)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)

    def test_creates_revenue_fields(self):
        req = self._transfer("В кассу: Сейф")
        req.refresh_from_db()  # Request.save() overwrites title with the tenant name
        dest = resolve_transfer_destination(req)
        revenue, created = ensure_transfer_revenue(request_obj=req, destination=dest)
        self.assertTrue(created)
        self.assertEqual(revenue.external_id, f"cash-{req.pk}")
        self.assertIsNotNone(revenue.source_year)
        self.assertTrue(revenue.confirmed)
        self.assertEqual(revenue.created_by_id, 1)
        self.assertEqual(revenue.wallet, self.safe)
        self.assertEqual(revenue.total_sum, req.amount)
        self.assertEqual(revenue.currency, "UZS")
        self.assertEqual(revenue.operation, f"Перевод между кассами {req.title}")
        self.assertEqual(revenue.operation, "Перевод между кассами Lemonfit AQUA")
        self.assertEqual(revenue.payload, {"source": "cash_desk_transfer", "request_id": req.pk})
        again, created_again = ensure_transfer_revenue(request_obj=req, destination=dest)
        self.assertFalse(created_again)
        self.assertEqual(again.pk, revenue.pk)
