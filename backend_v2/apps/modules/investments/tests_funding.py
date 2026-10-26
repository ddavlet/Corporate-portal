from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.modules.cashier.models import CashExpense
from apps.modules.investments.funding import register_funding_policies
from apps.modules.investments.models import (
    InvestmentApprovalConfigStep,
    InvestmentFundingConfig,
    ProjectInvestment,
)
from apps.modules.requests import payment_type_policies as registry
from apps.modules.requests.models import (
    Request,
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
class InvestmentFundingModeTests(APITestCase):
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
