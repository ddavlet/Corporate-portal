from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.modules.requests import payment_type_policies as registry
from apps.modules.requests.models import (
    Request,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
)
from apps.modules.wallets.models import CashRegister, Wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

PT = Request.PAYMENT_TYPE_INVEST_CASH


class FakePolicy:
    def __init__(self, *, available=True, wallet=None, hint=None):
        self.available = available
        self.wallet = wallet
        self.hint = hint

    def is_available(self, *, tenant):
        return self.available

    def normalize_attrs(self, *, tenant, attrs, instance):
        if self.wallet is not None:
            attrs["wallet_ref"] = self.wallet
        return attrs

    def form_hint(self, *, tenant):
        return self.hint


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class PaymentTypePolicyRegistryTests(APITestCase):
    def setUp(self):
        registry._reset_registry_for_tests()
        self.tenant = Tenant.objects.create(name="PolCo", subdomain="polco", is_active=True)
        self.admin = User.objects.create_user(username="pol_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "polco.example.com"

        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        for pt in ("Наличные", PT):
            pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type=pt, is_enabled=True)
            RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.admin)

        register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main")
        self.wallet_policy = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=register
        )
        register2 = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Other")
        self.wallet_client = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=register2
        )
        self.client.force_authenticate(self.admin)

    def tearDown(self):
        registry._reset_registry_for_tests()

    def _payload(self, **extra):
        data = {
            "title": "T",
            "description": "",
            "amount": 10,
            "currency": "UZS",
            "payment_type": PT,
            "urgency": "Обычно",
            "billing_date": "2026-01-01",
            "requester": self.admin.id,
        }
        data.update(extra)
        return data

    def test_unavailable_policy_rejects_create(self):
        registry.register_payment_type_policy(PT, FakePolicy(available=False))
        res = self.client.post("/api/requests/", self._payload(), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertIn("payment_type", res.data)

    def test_normalize_attrs_overrides_wallet(self):
        registry.register_payment_type_policy(PT, FakePolicy(wallet=self.wallet_policy))
        res = self.client.post(
            "/api/requests/",
            self._payload(wallet_ref=self.wallet_client.id),
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Request.objects.get(pk=res.data["id"]).wallet_ref_id, self.wallet_policy.id)

    def test_mutation_guard_blocks_amount_change(self):
        obj = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Inv",
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

        def guard(request_obj, attrs):
            if request_obj.pk == obj.pk and "amount" in attrs:
                return "Заявка входит во вложение №5"
            return None

        registry.register_request_mutation_guard(guard)
        res = self.client.patch(
            f"/api/requests/{obj.pk}/", {"amount": 99}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Заявка входит во вложение №5", str(res.data))
        obj.refresh_from_db()
        self.assertEqual(obj.amount, Decimal("10"))

    def test_form_options_hides_unavailable_and_adds_hint(self):
        hint = {"wallet_id": self.wallet_policy.id, "wallet_label": "Main", "currency": "UZS"}
        registry.register_payment_type_policy(PT, FakePolicy(hint=hint))
        res = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        by_type = {p["payment_type"]: p for p in res.data["payment_types"]}
        self.assertEqual(by_type[PT]["funding_hint"], hint)
        self.assertIsNone(by_type["Наличные"]["funding_hint"])

        registry.register_payment_type_policy(PT, FakePolicy(available=False))
        res = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        types = [p["payment_type"] for p in res.data["payment_types"]]
        self.assertNotIn(PT, types)
        self.assertIn("Наличные", types)
