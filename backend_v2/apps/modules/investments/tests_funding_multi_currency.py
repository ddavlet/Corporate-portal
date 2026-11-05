"""Инвестиционный режим: дополнительные инвест-кассы в других валютах (одна касса на валюту)."""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import override_settings

from apps.modules.cashier.models import CashRevenue
from apps.modules.investments import tests_funding as base
from apps.modules.investments.models import (
    CbuExchangeRate,
    InvestCompany,
    InvestmentFundingConfig,
    ProjectInvestment,
)
from apps.modules.investments.services import CbuRateFetchError
from apps.modules.requests.models import Request
from apps.modules.wallets.models import CashRegister, Wallet

# Модуль импортируется целиком (не классы), чтобы раннер не прогонял чужие тесты повторно.
FUNDING_URL = base.FUNDING_URL
INV_CASH = base.INV_CASH


class _MultiCurrencyMixin:
    def _make_cash_wallet(self, currency, name):
        register = CashRegister.objects.create(tenant=self.tenant, currency=currency, name=name)
        return Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency=currency, cash_register=register
        )

    def _add_usd_wallets(self):
        self.usd_wallet = self._make_cash_wallet("USD", "Инвест касса USD")
        self.usd_wallet_2 = self._make_cash_wallet("USD", "Ещё USD")

    def _enable_mode_with_usd(self):
        self._enable_mode()
        res = self._put_funding(extra_cash_wallet_ids=[self.usd_wallet.id])
        self.assertEqual(res.status_code, 200, res.data)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentFundingExtraCashWalletConfigTests(_MultiCurrencyMixin, base._FundingModeTestBase):
    def setUp(self):
        super().setUp()
        self._add_usd_wallets()

    def test_extra_cash_wallets_saved_and_returned(self):
        self._enable_mode_with_usd()
        res = self.client.get(FUNDING_URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["extra_cash_wallet_ids"], [self.usd_wallet.id])
        self.assertEqual(res.data["cash_wallet_id"], self.cash_wallet.id)
        cfg = InvestmentFundingConfig.objects.get(tenant=self.tenant)
        self.assertEqual([w.id for w in cfg.funding_cash_wallets()], [self.cash_wallet.id, self.usd_wallet.id])

    def test_extra_wallet_in_primary_currency_rejected(self):
        self._setup_chain()
        res = self._put_funding(extra_cash_wallet_ids=[self.other_cash_wallet.id])
        self.assertEqual(res.status_code, 400)
        self.assertIn("extra_cash_wallet_ids", res.data)

    def test_two_extra_wallets_same_currency_rejected(self):
        self._setup_chain()
        res = self._put_funding(extra_cash_wallet_ids=[self.usd_wallet.id, self.usd_wallet_2.id])
        self.assertEqual(res.status_code, 400)
        self.assertIn("extra_cash_wallet_ids", res.data)

    def test_extra_wallet_must_be_cash_of_tenant(self):
        self._setup_chain()
        res = self._put_funding(extra_cash_wallet_ids=[self.bank_wallet.id])
        self.assertEqual(res.status_code, 400)
        self.assertIn("extra_cash_wallet_ids", res.data)

    def test_put_without_extra_key_keeps_extras_and_empty_list_clears(self):
        self._enable_mode_with_usd()
        res = self._put_funding()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["extra_cash_wallet_ids"], [self.usd_wallet.id])

        res = self._put_funding(extra_cash_wallet_ids=[])
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["extra_cash_wallet_ids"], [])
        # Сама касса остаётся — отключается только её участие в режиме.
        self.assertTrue(Wallet.objects.filter(pk=self.usd_wallet.id).exists())

    def test_primary_switched_to_extra_currency_conflicts_with_stored_extra(self):
        self._enable_mode_with_usd()
        res = self._put_funding(cash_wallet_id=self.usd_wallet_2.id)
        self.assertEqual(res.status_code, 400)
        self.assertIn("extra_cash_wallet_ids", res.data)

    # ---- заявки «Инвест. наличные» --------------------------------------------------------------

    def test_invest_cash_request_picks_wallet_by_currency(self):
        self._enable_mode_with_usd()
        usd = self._post_request(INV_CASH, currency="USD", amount=6000)
        self.assertEqual(usd.status_code, 201, usd.data)
        self.assertEqual(Request.objects.get(pk=usd.data["id"]).wallet_ref_id, self.usd_wallet.id)

        uzs = self._post_request(INV_CASH, currency="UZS")
        self.assertEqual(uzs.status_code, 201, uzs.data)
        self.assertEqual(Request.objects.get(pk=uzs.data["id"]).wallet_ref_id, self.cash_wallet.id)

        eur = self._post_request(INV_CASH, currency="EUR")
        self.assertEqual(eur.status_code, 400)
        self.assertIn("currency", eur.data)

    def test_usd_request_rejected_without_usd_invest_wallet(self):
        self._enable_mode()
        res = self._post_request(INV_CASH, currency="USD")
        self.assertEqual(res.status_code, 400)
        self.assertIn("currency", res.data)

    def test_currency_change_on_draft_moves_wallet(self):
        self._enable_mode_with_usd()
        created = self._post_request(INV_CASH)
        self.assertEqual(created.status_code, 201, created.data)
        req_id = created.data["id"]
        Request.objects.filter(pk=req_id).update(status=Request.STATUS_DRAFT)

        res = self.client.patch(f"/api/requests/{req_id}/", {"currency": "USD"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.data)
        req = Request.objects.get(pk=req_id)
        self.assertEqual(req.currency, "USD")
        self.assertEqual(req.wallet_ref_id, self.usd_wallet.id)

    def test_form_options_hint_lists_all_invest_cash_wallets(self):
        self._enable_mode_with_usd()
        res = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.data)
        row = next(r for r in res.data["payment_types"] if r["payment_type"] == INV_CASH)
        hint = row["funding_hint"]
        self.assertEqual(hint["currency"], "UZS")
        self.assertEqual(
            [(w["wallet_id"], w["currency"]) for w in hint["wallets"]],
            [(self.cash_wallet.id, "UZS"), (self.usd_wallet.id, "USD")],
        )

    def test_cash_investment_in_extra_currency_allowed(self):
        inv = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 3, 1),
            amount=Decimal("500"),
            currency="USD",
            created_by=self.admin,
        )
        self._enable_mode_with_usd()
        res = self.client.patch(
            f"/api/investments/project-investments/{inv.pk}/",
            {"funding_method": "cash", "currency": "USD"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.data)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentFundingExtraCashWalletCollectTests(_MultiCurrencyMixin, base._FundingModeTestBase):
    """Сбор вложения и приход: долларовая заявка → долларовое вложение → приход в долларовую кассу."""

    _make_request = base.InvestmentFundingCollectTests._make_request
    _collect = base.InvestmentFundingCollectTests._collect
    _collect_ok = base.InvestmentFundingCollectTests._collect_ok
    _pool = base.InvestmentFundingCollectTests._pool
    _ids = staticmethod(base.InvestmentFundingCollectTests._ids)
    _approve = base.InvestmentFundingRevenueTests._approve

    def setUp(self):
        super().setUp()
        send_patcher = patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
        send_patcher.start().return_value = MagicMock()
        self.addCleanup(send_patcher.stop)
        CbuExchangeRate.objects.get_or_create(date=date(2026, 1, 1), defaults={"usd_uzs_rate": Decimal("12600")})
        rate_patcher = patch(
            "apps.modules.investments.services.fetch_cbu_usd_uzs_rate", side_effect=CbuRateFetchError("offline")
        )
        rate_patcher.start()
        self.addCleanup(rate_patcher.stop)
        self.company = InvestCompany.objects.create(tenant=self.tenant, name="Инвестор", created_by=self.admin)

    def test_pool_includes_requests_of_all_invest_cash_wallets(self):
        self._add_usd_wallets()
        self._enable_mode_with_usd()
        uzs = self._make_request(INV_CASH, amount="100")
        usd = self._make_request(INV_CASH, amount="6000", currency="USD", wallet=self.usd_wallet)
        foreign_usd = self._make_request(INV_CASH, amount="5", currency="USD", wallet=self.usd_wallet_2)

        ids = self._ids(self._pool()["cash"])
        self.assertEqual(ids, {uzs.id, usd.id})
        self.assertNotIn(foreign_usd.id, ids)

    def test_usd_investment_confirmed_creates_revenue_in_usd_wallet(self):
        self._add_usd_wallets()
        self._enable_mode_with_usd()
        uzs = self._make_request(INV_CASH, amount="100")
        usd = self._make_request(INV_CASH, amount="6000", currency="USD", wallet=self.usd_wallet)

        created = self._collect_ok("cash", [uzs, usd])
        by_currency = {row["currency"]: row["id"] for row in created}
        self.assertEqual(set(by_currency), {"UZS", "USD"})

        self._approve(by_currency["USD"])
        revenue = CashRevenue.objects.get(tenant=self.tenant, payload__project_investment_id=by_currency["USD"])
        self.assertEqual(revenue.wallet_id, self.usd_wallet.id)
        self.assertEqual(revenue.currency, "USD")
        self.assertEqual(revenue.total_sum, Decimal("6000"))

        self._approve(by_currency["UZS"])
        revenue = CashRevenue.objects.get(tenant=self.tenant, payload__project_investment_id=by_currency["UZS"])
        self.assertEqual(revenue.wallet_id, self.cash_wallet.id)
