from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.investments.funding import INVESTOR_DEPOSIT_OPERATION, register_funding_policies
from apps.modules.investments.funding_pool import build_default_comment
from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfigStep,
    InvestmentFundingConfig,
    ProjectInvestment,
    ProjectInvestmentApproval,
    ProjectInvestmentRequestLink,
)
from apps.modules.requests import payment_type_policies as registry
from apps.modules.requests.models import (
    Request,
    RequestComment,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
)
from apps.modules.requests.services import create_expense_for_request_payment
from apps.modules.wallets.models import BankAccount, CashRegister, Wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

INV_CASH = Request.PAYMENT_TYPE_INVEST_CASH
INV_TRANSFER = Request.PAYMENT_TYPE_INVEST_TRANSFER
FUNDING_URL = "/api/investments/funding-config/"


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class _FundingModeTestBase(APITestCase):
    """Общая фикстура инвестиционного режима: тенант, цепочка согласования вложений, кассы, счёт."""

    def setUp(self):
        self._registry_snapshot = registry._snapshot_registry_for_tests()
        register_funding_policies()

        self.tenant = Tenant.objects.create(name="FundCo", subdomain="fundco", is_active=True)
        self.host = "fundco.example.com"
        self.admin = User.objects.create_user(username="fund_admin", password="x")
        self.approver = User.objects.create_user(
            username="fund_appr", password="x", telegram_chat_id=255001, telegram_from_id=277001
        )
        for user in (self.admin, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_DIRECTOR)
        for key in ("investments", "requests", "cash", "bank"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)

        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Инвест касса")
        self.cash_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=cash_register
        )
        other_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Другая")
        self.other_cash_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=other_register
        )
        account = BankAccount.objects.create(tenant=self.tenant, label="Инвест счёт", is_default=False)
        self.bank_wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.BANK, currency="UZS", bank_account=account
        )
        self.client.force_authenticate(self.admin)

    def tearDown(self):
        registry._restore_registry_for_tests(self._registry_snapshot)

    # ---- helpers -------------------------------------------------------------------------------

    def _setup_chain(self):
        res = self.client.put(
            "/api/investments/project-approval-config/",
            {
                "is_enabled": True,
                "steps": [
                    {
                        "step": 1,
                        "step_type": InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                        "is_enabled": True,
                        "approver_user_ids": [self.approver.id],
                    }
                ],
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.data)

    def _put_funding(self, **overrides):
        payload = {
            "is_enabled": True,
            "cash_wallet_id": self.cash_wallet.id,
            "bank_wallet_id": self.bank_wallet.id,
        }
        payload.update(overrides)
        return self.client.put(FUNDING_URL, payload, format="json", HTTP_HOST=self.host)

    def _enable_mode(self):
        self._setup_chain()
        res = self._put_funding()
        self.assertEqual(res.status_code, 200, res.data)
        cfg = RequestFormConfig.objects.get(tenant=self.tenant)
        for pt_cfg in cfg.payment_types.all():
            RequestFormPaymentTypeRequester.objects.get_or_create(payment_type_config=pt_cfg, user=self.admin)

    def _request_payload(self, payment_type, **extra):
        data = {
            "title": "Инвест",
            "description": "",
            "amount": 10,
            "currency": "UZS",
            "payment_type": payment_type,
            "urgency": "Обычно",
            "billing_date": "2026-01-01",
            "requester": self.admin.id,
        }
        data.update(extra)
        return data

    def _post_request(self, payment_type, **extra):
        return self.client.post(
            "/api/requests/", self._request_payload(payment_type, **extra), format="json", HTTP_HOST=self.host
        )


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentFundingModeTests(_FundingModeTestBase):
    # ---- вложение: способ внесения ---------------------------------------------------------------

    def test_create_investment_requires_funding_method(self):
        url = "/api/investments/project-investments/"
        body = {"date": "2026-04-15", "amount": "1000.00", "currency": "USD", "comment": ""}
        res = self.client.post(url, body, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertIn("funding_method", res.data)

        res = self.client.post(url, {**body, "funding_method": "cash"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(ProjectInvestment.objects.get(pk=res.data["id"]).funding_method, "cash")

    def test_legacy_investment_without_method_still_editable(self):
        inv = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 3, 1),
            amount=Decimal("500"),
            currency="USD",
            created_by=self.admin,
        )
        res = self.client.patch(
            f"/api/investments/project-investments/{inv.pk}/",
            {"comment": "updated"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.data)
        inv.refresh_from_db()
        self.assertEqual(inv.comment, "updated")
        self.assertIsNone(inv.funding_method)

    def test_cash_investment_currency_must_match_cash_wallet(self):
        inv = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 3, 1),
            amount=Decimal("500"),
            currency="USD",
            created_by=self.admin,
        )
        self._enable_mode()
        res = self.client.patch(
            f"/api/investments/project-investments/{inv.pk}/",
            {"funding_method": "cash", "currency": "USD"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("currency", res.data)

    # ---- настройки режима -----------------------------------------------------------------------

    def test_enable_mode_requires_approval_chain(self):
        res = self._put_funding()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["detail"], "Сначала настройте согласование заявок на вложение.")

    def test_enable_mode_rejects_bank_wallet_as_cash(self):
        self._setup_chain()
        res = self._put_funding(cash_wallet_id=self.bank_wallet.id)
        self.assertEqual(res.status_code, 400)
        self.assertIn("cash_wallet_id", res.data)

    def test_enable_mode_sets_enabled_at_once_and_form_configs(self):
        self._setup_chain()
        first = self._put_funding()
        self.assertEqual(first.status_code, 200, first.data)
        self.assertIsNotNone(first.data["enabled_at"])
        self.assertTrue(first.data["has_project_approval_chain"])
        self.assertEqual(first.data["cash_wallet_currency"], "UZS")
        enabled_at = InvestmentFundingConfig.objects.get(tenant=self.tenant).enabled_at

        second = self._put_funding()
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(InvestmentFundingConfig.objects.get(tenant=self.tenant).enabled_at, enabled_at)

        types = set(
            RequestFormPaymentTypeConfig.objects.filter(config__tenant=self.tenant, is_enabled=True).values_list(
                "payment_type", flat=True
            )
        )
        self.assertEqual(types, {INV_CASH, INV_TRANSFER})
        cash_cfg = RequestFormPaymentTypeConfig.objects.get(config__tenant=self.tenant, payment_type=INV_CASH)
        self.assertEqual(cash_cfg.default_currency, "UZS")

    # ---- заявки инвест-типов ---------------------------------------------------------------------

    def test_invest_cash_request_forces_wallet_and_currency(self):
        self._enable_mode()
        res = self._post_request(INV_CASH, wallet_ref=self.other_cash_wallet.id)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Request.objects.get(pk=res.data["id"]).wallet_ref_id, self.cash_wallet.id)

        res = self._post_request(INV_CASH, currency="USD")
        self.assertEqual(res.status_code, 400)
        self.assertIn("currency", res.data)

    def test_invest_transfer_request_uses_bank_wallet(self):
        self._enable_mode()
        res = self._post_request(INV_TRANSFER)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Request.objects.get(pk=res.data["id"]).wallet_ref_id, self.bank_wallet.id)

    def test_invest_types_unavailable_when_mode_disabled(self):
        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        for pt in ("Наличные", INV_CASH):
            pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=form_cfg, payment_type=pt, is_enabled=True)
            RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.admin)

        res = self._post_request(INV_CASH)
        self.assertEqual(res.status_code, 400)
        self.assertIn("payment_type", res.data)

        res = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        types = [p["payment_type"] for p in res.data["payment_types"]]
        self.assertNotIn(INV_CASH, types)
        self.assertIn("Наличные", types)

    def test_existing_invest_request_survives_mode_disabled(self):
        self._enable_mode()
        created = self._post_request(INV_CASH)
        self.assertEqual(created.status_code, 201, created.data)
        req_id = created.data["id"]
        Request.objects.filter(pk=req_id).update(status=Request.STATUS_DRAFT)

        res = self._put_funding(is_enabled=False)
        self.assertEqual(res.status_code, 200, res.data)

        res = self.client.patch(
            f"/api/requests/{req_id}/",
            {"description": "новое", "wallet_ref": self.other_cash_wallet.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.data)
        req = Request.objects.get(pk=req_id)
        self.assertEqual(req.description, "новое")
        self.assertEqual(req.wallet_ref_id, self.cash_wallet.id)

        Request.objects.filter(pk=req_id).update(status=Request.STATUS_APPROVED)
        req.refresh_from_db()
        target, expense_id = create_expense_for_request_payment(request_obj=req, actor_user=self.admin)
        self.assertEqual(target, "cash")
        self.assertEqual(CashExpense.objects.get(pk=expense_id).wallet_id, self.cash_wallet.id)

    def test_existing_invest_request_keeps_wallet_after_cash_reconfigured(self):
        self._enable_mode()
        created = self._post_request(INV_CASH)
        self.assertEqual(created.status_code, 201, created.data)
        req_id = created.data["id"]
        Request.objects.filter(pk=req_id).update(status=Request.STATUS_DRAFT)

        res = self._put_funding(cash_wallet_id=self.other_cash_wallet.id)
        self.assertEqual(res.status_code, 200, res.data)

        res = self.client.patch(
            f"/api/requests/{req_id}/", {"description": "новое"}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Request.objects.get(pk=req_id).wallet_ref_id, self.cash_wallet.id)

    def test_investment_comment_patch_ignores_currency_mismatch(self):
        inv = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 3, 1),
            amount=Decimal("500"),
            currency="USD",
            funding_method="cash",
            created_by=self.admin,
        )
        self._enable_mode()
        res = self.client.patch(
            f"/api/investments/project-investments/{inv.pk}/",
            {"comment": "только комментарий"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.data)

    def test_put_without_wallet_keys_keeps_stored_wallets(self):
        self._enable_mode()
        res = self.client.put(FUNDING_URL, {"is_enabled": False}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.data)
        cfg = InvestmentFundingConfig.objects.get(tenant=self.tenant)
        self.assertFalse(cfg.is_enabled)
        self.assertEqual(cfg.cash_wallet_id, self.cash_wallet.id)
        self.assertEqual(cfg.bank_wallet_id, self.bank_wallet.id)

    def test_request_delete_hook_calls_mutation_guard(self):
        obj = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Del",
            description="",
            amount=Decimal("10"),
            currency="UZS",
            payment_type="Наличные",
            urgency="Обычно",
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="Co",
        )
        registry.register_request_mutation_guard(lambda request_obj, attrs: "Удаление запрещено вложением")

        res = self.client.delete(f"/api/requests/{obj.pk}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Удаление запрещено вложением", str(res.data))
        self.assertTrue(Request.objects.filter(pk=obj.pk).exists())


POOL_URL = "/api/investments/project-investments/funding-pool/"
COLLECT_URL = "/api/investments/project-investments/from-requests/"
INVESTMENTS_URL = "/api/investments/project-investments/"


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentFundingCollectTests(_FundingModeTestBase):
    """Пул заявок, сбор вложений по заявкам, защита собранного."""

    def setUp(self):
        super().setUp()
        send_patcher = patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
        send_patcher.start().return_value = MagicMock()
        self.addCleanup(send_patcher.stop)
        rate_patcher = patch(
            "apps.modules.investments.services.fetch_cbu_usd_uzs_rate", return_value=Decimal("12600")
        )
        rate_patcher.start()
        self.addCleanup(rate_patcher.stop)
        self.company = InvestCompany.objects.create(tenant=self.tenant, name="Инвестор", created_by=self.admin)

    # ---- helpers -------------------------------------------------------------------------------

    def _make_request(
        self,
        payment_type,
        *,
        amount="10",
        currency="UZS",
        status=Request.STATUS_APPROVED,
        wallet=None,
        purpose="",
        description="",
        submitted_at=None,
    ):
        if wallet is None:
            wallet = self.bank_wallet if payment_type == INV_TRANSFER else self.cash_wallet
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            description=description,
            amount=Decimal(amount),
            currency=currency,
            payment_type=payment_type,
            payment_purpose=purpose,
            urgency="Обычно",
            billing_date=date(2026, 1, 1),
            status=status,
            submitted_at=submitted_at or timezone.now(),
            wallet_ref=wallet,
            company_payer="Co",
        )

    def _collect(self, funding_method, request_ids, **extra):
        body = {"funding_method": funding_method, "request_ids": request_ids, "company": self.company.id}
        body.update(extra)
        return self.client.post(COLLECT_URL, body, format="json", HTTP_HOST=self.host)

    def _collect_ok(self, funding_method, requests):
        res = self._collect(funding_method, [r.id for r in requests])
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["investments"]

    def _pool(self):
        res = self.client.get(POOL_URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.data)
        return res.data

    @staticmethod
    def _ids(group):
        return {row["id"] for row in group["requests"]}

    # ---- пул -----------------------------------------------------------------------------------

    def test_pool_contains_approved_and_payed_invest_and_transfer_requests(self):
        self._enable_mode()
        enabled_at = InvestmentFundingConfig.objects.get(tenant=self.tenant).enabled_at
        expense = self._make_request(INV_CASH, amount="10", description="компьютер")
        transfer = self._make_request(
            "Наличные", amount="5", status=Request.STATUS_PAYED, purpose="Перевод между кассами"
        )
        draft = self._make_request(INV_CASH, status=Request.STATUS_DRAFT)
        rejected = self._make_request(INV_CASH, status=Request.STATUS_REJECTED)
        other_cash = self._make_request("Наличные", wallet=self.other_cash_wallet)
        before_mode = self._make_request(INV_CASH, submitted_at=enabled_at - timedelta(days=1))

        data = self._pool()
        cash_ids = self._ids(data["cash"])
        self.assertEqual(cash_ids, {expense.id, transfer.id})
        for excluded in (draft, rejected, other_cash, before_mode):
            self.assertNotIn(excluded.id, cash_ids)
        rows = {row["id"]: row for row in data["cash"]["requests"]}
        self.assertEqual(rows[transfer.id]["kind"], "transfer")
        self.assertTrue(rows[transfer.id]["is_payed"])
        self.assertEqual(rows[expense.id]["kind"], "expense")
        self.assertFalse(rows[expense.id]["is_payed"])
        self.assertEqual(data["cash"]["totals"], [{"currency": "UZS", "amount": "15.00", "count": 2}])
        self.assertEqual(data["bank_transfer"]["requests"], [])
        self.assertTrue(data["approval_chain_ok"])

    def test_pool_bank_contains_only_invest_transfer(self):
        self._enable_mode()
        invest_transfer = self._make_request(INV_TRANSFER)
        plain_transfer = self._make_request("Перечисление", wallet=self.bank_wallet)

        data = self._pool()
        self.assertEqual(self._ids(data["bank_transfer"]), {invest_transfer.id})
        self.assertNotIn(plain_transfer.id, self._ids(data["cash"]))

    def test_default_comment_lists_requests(self):
        expense = self._make_request(INV_CASH, description="компьютер")
        transfer = self._make_request("Наличные", purpose="Перевод между кассами", description="в сейф")
        self.assertEqual(
            build_default_comment([expense, transfer]),
            f"На основании заявок №{expense.id}, №{transfer.id}. "
            f"№{expense.id} — компьютер; №{transfer.id} — перевод между кассами",
        )

    # ---- сбор ----------------------------------------------------------------------------------

    def test_collect_splits_by_currency(self):
        self._enable_mode()
        uzs_a = self._make_request(INV_TRANSFER, amount="5000000")
        uzs_b = self._make_request(INV_TRANSFER, amount="2000000")
        usd = self._make_request(INV_TRANSFER, amount="100", currency="USD")

        created = self._collect_ok("bank_transfer", [uzs_a, uzs_b, usd])
        self.assertEqual(len(created), 2)
        by_currency = {row["currency"]: ProjectInvestment.objects.get(pk=row["id"]) for row in created}
        self.assertEqual(set(by_currency), {"UZS", "USD"})
        self.assertEqual(by_currency["UZS"].amount, Decimal("7000000.00"))
        self.assertEqual(by_currency["USD"].amount, Decimal("100.00"))
        for inv in by_currency.values():
            self.assertEqual(inv.funding_method, ProjectInvestment.FundingMethod.BANK_TRANSFER)
            self.assertFalse(inv.confirmed)
            self.assertEqual(inv.company_id, self.company.id)
        # Пустой comment → текст по умолчанию на каждую валютную группу.
        self.assertEqual(by_currency["UZS"].comment, f"На основании заявок №{uzs_a.id}, №{uzs_b.id}.")
        self.assertEqual(by_currency["USD"].comment, f"На основании заявки №{usd.id}.")

        uzs_inv = by_currency["UZS"]
        self.assertEqual(
            set(uzs_inv.request_links.values_list("request_id", flat=True)), {uzs_a.id, uzs_b.id}
        )
        self.assertEqual(
            set(by_currency["USD"].request_links.values_list("request_id", flat=True)), {usd.id}
        )
        uzs_row = next(row for row in created if row["currency"] == "UZS")
        self.assertEqual({r["id"] for r in uzs_row["source_requests"]}, {uzs_a.id, uzs_b.id})

        for req, inv in ((uzs_a, uzs_inv), (uzs_b, uzs_inv), (usd, by_currency["USD"])):
            self.assertTrue(
                RequestComment.objects.filter(
                    request=req, body=f"Заявка включена в заявку на вложение №{inv.id}."
                ).exists()
            )
        self.assertEqual(self._pool()["bank_transfer"]["requests"], [])

    def test_collect_twice_same_requests_rejected(self):
        self._enable_mode()
        req = self._make_request(INV_CASH)
        self._collect_ok("cash", [req])

        res = self._collect("cash", [req.id])
        self.assertEqual(res.status_code, 400)
        self.assertIn("request_ids", res.data)
        self.assertEqual(ProjectInvestment.objects.filter(tenant=self.tenant).count(), 1)

    def test_collect_empty_request_ids_rejected(self):
        self._enable_mode()
        res = self._collect("cash", [])
        self.assertEqual(res.status_code, 400)
        self.assertIn("request_ids", res.data)

    def test_rejected_investment_releases_requests(self):
        self._enable_mode()
        first = self._make_request(INV_CASH, amount="10")
        second = self._make_request(INV_CASH, amount="20")
        old_id = self._collect_ok("cash", [first, second])[0]["id"]
        self.assertEqual(self._pool()["cash"]["requests"], [])

        approval = ProjectInvestmentApproval.objects.get(project_investment_id=old_id, step=1)
        res = self.client.post(
            f"/api/investments/project-approvals/{approval.id}/decision/",
            {"decision": "rejected"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.data)

        self.assertEqual(self._ids(self._pool()["cash"]), {first.id, second.id})
        new_id = self._collect_ok("cash", [first, second])[0]["id"]
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(ProjectInvestmentRequestLink.objects.filter(project_investment_id=old_id).count(), 2)
        self.assertEqual(ProjectInvestmentRequestLink.objects.filter(request=first).count(), 2)

    # ---- защита собранного ---------------------------------------------------------------------

    def test_collected_request_amount_locked(self):
        self._enable_mode()
        req = self._make_request(INV_CASH, amount="10")
        inv_id = self._collect_ok("cash", [req])[0]["id"]

        res = self.client.patch(f"/api/requests/{req.id}/", {"amount": "999"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn(f"входит в заявку на вложение №{inv_id}", str(res.data))
        req.refresh_from_db()
        self.assertEqual(req.amount, Decimal("10.00"))

        res = self.client.delete(f"/api/requests/{req.id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertIn("входит в заявку на вложение №", str(res.data))
        self.assertTrue(Request.objects.filter(pk=req.pk).exists())

    def test_collected_investment_amount_locked(self):
        self._enable_mode()
        req = self._make_request(INV_CASH, amount="10")
        inv_id = self._collect_ok("cash", [req])[0]["id"]
        url = f"{INVESTMENTS_URL}{inv_id}/"

        res = self.client.patch(url, {"amount": "11.00"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertIn("amount", res.data)

        res = self.client.patch(url, {"comment": "уточнение"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.data)
        inv = ProjectInvestment.objects.get(pk=inv_id)
        self.assertEqual(inv.comment, "уточнение")
        self.assertEqual(inv.amount, Decimal("10.00"))

    def test_investment_with_cash_revenue_cannot_be_deleted(self):
        self._enable_mode()
        with_revenue = self._make_request(INV_CASH, amount="10")
        without_revenue = self._make_request(INV_CASH, amount="20", currency="UZS")
        inv_id = self._collect_ok("cash", [with_revenue])[0]["id"]
        other_id = self._collect_ok("cash", [without_revenue])[0]["id"]
        CashRevenue.objects.create(
            tenant=self.tenant,
            external_id=f"inv-{inv_id}",
            source_year=timezone.now().year,
            revenue_at=timezone.now(),
            currency="UZS",
            operation=INVESTOR_DEPOSIT_OPERATION,
            total_sum=Decimal("10"),
            payload={"project_investment_id": inv_id},
            created_by=self.admin,
            wallet=self.cash_wallet,
        )

        res = self.client.delete(f"{INVESTMENTS_URL}{inv_id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["detail"], "По вложению уже создан приход в кассу — удалить нельзя.")
        self.assertTrue(ProjectInvestment.objects.filter(pk=inv_id).exists())

        res = self.client.delete(f"{INVESTMENTS_URL}{other_id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 204)
        self.assertIn(without_revenue.id, self._ids(self._pool()["cash"]))

    # ---- режим выключен / ручное создание -------------------------------------------------------

    def test_pool_forbidden_when_mode_disabled(self):
        req = self._make_request(INV_CASH)
        res = self.client.get(POOL_URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data["detail"], "Инвестиционный режим выключен.")

        res = self._collect("cash", [req.id])
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data["detail"], "Инвестиционный режим выключен.")
        self.assertFalse(ProjectInvestment.objects.filter(tenant=self.tenant).exists())

    def test_source_request_filter(self):
        self._enable_mode()
        req = self._make_request(INV_CASH)
        inv_id = self._collect_ok("cash", [req])[0]["id"]
        ProjectInvestment.objects.create(
            tenant=self.tenant, date=date(2026, 3, 1), amount=Decimal("5"), currency="UZS", created_by=self.admin
        )

        res = self.client.get(f"{INVESTMENTS_URL}?source_request={req.id}", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.data)
        rows = res.data["results"]
        self.assertEqual([row["id"] for row in rows], [inv_id])
        self.assertEqual([r["id"] for r in rows[0]["source_requests"]], [req.id])

    def test_manual_create_forbidden_when_mode_enabled(self):
        self._enable_mode()
        existing = ProjectInvestment.objects.create(
            tenant=self.tenant, date=date(2026, 3, 1), amount=Decimal("5"), currency="UZS", created_by=self.admin
        )
        body = {"date": "2026-04-15", "amount": "1000.00", "currency": "UZS", "funding_method": "bank_transfer"}

        res = self.client.post(INVESTMENTS_URL, body, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertIn("создаются только через «Собрать по заявкам»", str(res.data))
        self.assertEqual(ProjectInvestment.objects.filter(tenant=self.tenant).count(), 1)

        res = self.client.patch(
            f"{INVESTMENTS_URL}{existing.id}/", {"comment": "правка"}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 200, res.data)

        res = self._put_funding(is_enabled=False)
        self.assertEqual(res.status_code, 200, res.data)
        res = self.client.post(INVESTMENTS_URL, body, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.data)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentFundingRevenueTests(_FundingModeTestBase):
    """Приход в инвестиционную кассу при подтверждении вложения «наличными»."""

    # Хелперы сбора переиспользуем без наследования (иначе повторятся тесты сбора).
    _make_request = InvestmentFundingCollectTests._make_request
    _collect = InvestmentFundingCollectTests._collect
    _collect_ok = InvestmentFundingCollectTests._collect_ok

    def setUp(self):
        super().setUp()
        send_patcher = patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
        send_patcher.start().return_value = MagicMock()
        self.addCleanup(send_patcher.stop)
        rate_patcher = patch(
            "apps.modules.investments.services.fetch_cbu_usd_uzs_rate", return_value=Decimal("12600")
        )
        rate_patcher.start()
        self.addCleanup(rate_patcher.stop)
        self.company = InvestCompany.objects.create(tenant=self.tenant, name="Инвестор", created_by=self.admin)

    def _approve(self, inv_id):
        approval = ProjectInvestmentApproval.objects.get(project_investment_id=inv_id, step=1)
        res = self.client.post(
            f"/api/investments/project-approvals/{approval.id}/decision/",
            {"decision": "approved"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(ProjectInvestment.objects.get(pk=inv_id).confirmed)

    def _collect_and_approve(self, funding_method, payment_type, amount="10"):
        req = self._make_request(payment_type, amount=amount)
        inv_id = self._collect_ok(funding_method, [req])[0]["id"]
        self._approve(inv_id)
        return inv_id

    def test_confirmed_cash_investment_creates_revenue_in_invest_cash(self):
        self._enable_mode()
        inv_id = self._collect_and_approve("cash", INV_CASH, amount="10")

        revenues = CashRevenue.objects.filter(tenant=self.tenant)
        self.assertEqual(revenues.count(), 1)
        revenue = revenues.get()
        self.assertEqual(revenue.wallet_id, self.cash_wallet.id)
        self.assertEqual(revenue.total_sum, Decimal("10"))
        self.assertEqual(revenue.currency, "UZS")
        self.assertEqual(revenue.operation, INVESTOR_DEPOSIT_OPERATION)
        self.assertEqual(revenue.comment, f"На основании заявки на вложение №{inv_id}")
        self.assertIsNotNone(revenue.source_year)
        self.assertEqual(revenue.payload["project_investment_id"], inv_id)
        self.assertEqual(revenue.created_by_id, self.approver.id)

    def test_revenue_idempotent_on_resave(self):
        self._enable_mode()
        inv_id = self._collect_and_approve("cash", INV_CASH)

        inv = ProjectInvestment.objects.get(pk=inv_id)
        inv.save()
        inv.save(update_fields=["confirmed"])
        res = self.client.patch(
            f"{INVESTMENTS_URL}{inv_id}/", {"comment": "уточнение"}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 200, res.data)

        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)

    def test_bank_transfer_investment_creates_no_revenue(self):
        self._enable_mode()
        self._collect_and_approve("bank_transfer", INV_TRANSFER)
        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant).exists())

    def test_no_revenue_when_mode_disabled(self):
        inv = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 3, 1),
            amount=Decimal("10"),
            currency="UZS",
            funding_method=ProjectInvestment.FundingMethod.CASH,
            created_by=self.admin,
        )
        inv.confirmed = True
        inv.save()
        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant).exists())

    def test_delete_investment_with_revenue_forbidden(self):
        self._enable_mode()
        inv_id = self._collect_and_approve("cash", INV_CASH)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)

        res = self.client.delete(f"{INVESTMENTS_URL}{inv_id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertTrue(ProjectInvestment.objects.filter(pk=inv_id).exists())
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)

    def test_revenue_failure_rolls_back_confirmation(self):
        from apps.modules.investments.project_investment_approval_services import (
            route_project_investment_approvals,
        )

        self._enable_mode()
        req = self._make_request(INV_CASH)
        inv_id = self._collect_ok("cash", [req])[0]["id"]
        ProjectInvestmentApproval.objects.filter(project_investment_id=inv_id).update(
            decision=ProjectInvestmentApproval.DECISION_APPROVED, decided_at=timezone.now()
        )
        inv = ProjectInvestment.objects.get(pk=inv_id)

        with patch(
            "apps.modules.investments.funding_revenue.ensure_investor_cash_revenue",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                route_project_investment_approvals(project_investment=inv)

        self.assertFalse(ProjectInvestment.objects.get(pk=inv_id).confirmed)
        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant).exists())

    def test_no_revenue_on_wallet_currency_mismatch(self):
        self._enable_mode()
        inv = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 3, 1),
            amount=Decimal("10"),
            currency="USD",
            funding_method=ProjectInvestment.FundingMethod.CASH,
            created_by=self.admin,
        )
        inv.confirmed = True
        inv.save()
        self.assertTrue(ProjectInvestment.objects.get(pk=inv.id).confirmed)
        self.assertFalse(CashRevenue.objects.filter(tenant=self.tenant).exists())
