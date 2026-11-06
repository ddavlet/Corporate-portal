from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.cash_desk.fixtures import CashDeskFixtures
from apps.modules.cash_desk.models import CashRegisterTransferTarget
from apps.modules.requests.models import Request
from apps.modules.wallets.models import CashRegister, Wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


def url(request_id):
    return f"/api/cash-desk/transfers/{request_id}/target/"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TransferTargetApiTests(CashDeskFixtures, APITestCase):
    def setUp(self):
        self.make_fixtures()
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.client.force_authenticate(self.admin)

    def draft(self, **overrides):
        data = {
            "status": Request.STATUS_DRAFT,
            "payment_purpose": "Перевод между кассами",
            "wallet_ref": self.main,
            "payed_at": None,
        }
        data.update(overrides)
        return self.make_request(**data)

    def put(self, req, payload):
        return self.client.put(url(req.id), payload, format="json", HTTP_HOST=self.host)

    def test_same_currency_defaults_amount(self):
        req = self.draft()
        res = self.put(req, {"to_wallet_id": self.safe.id})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["to_wallet_id"], self.safe.id)
        self.assertEqual(res.data["currency"], "UZS")
        target = CashRegisterTransferTarget.objects.get(request=req)
        self.assertEqual(target.to_amount, Decimal("1500000.00"))
        self.assertEqual(target.source_amount, Decimal("1500000.00"))
        self.assertEqual(target.source_currency, "UZS")

    def test_cross_currency_requires_amount(self):
        req = self.draft()
        res = self.put(req, {"to_wallet_id": self.usd.id})
        self.assertEqual(res.status_code, 400)
        self.assertIn("detail", res.data)
        res = self.put(req, {"to_wallet_id": self.usd.id, "to_amount": "120"})
        self.assertEqual(res.status_code, 200, res.data)
        target = CashRegisterTransferTarget.objects.get(request=req)
        self.assertEqual(target.to_amount, Decimal("120.00"))
        self.assertEqual(target.source_amount, Decimal("1500000.00"))
        self.assertEqual(target.source_currency, "UZS")
        self.assertEqual(res.data["currency"], "USD")

    def test_same_currency_mismatched_amount_rejected(self):
        req = self.draft()
        res = self.put(req, {"to_wallet_id": self.safe.id, "to_amount": "1400000"})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(CashRegisterTransferTarget.objects.filter(request=req).exists())

    def test_rejects_non_draft(self):
        req = self.draft(status=Request.STATUS_PAYED)
        res = self.put(req, {"to_wallet_id": self.safe.id})
        self.assertEqual(res.status_code, 400)

    def test_rejects_non_transfer_purpose(self):
        req = self.draft(payment_purpose="Хозтовары")
        res = self.put(req, {"to_wallet_id": self.safe.id})
        self.assertEqual(res.status_code, 400)

    def test_rejects_source_wallet(self):
        req = self.draft()
        res = self.put(req, {"to_wallet_id": self.main.id})
        self.assertEqual(res.status_code, 400)

    def test_rejects_foreign_wallet(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        register = CashRegister.objects.create(
            tenant=other, currency="UZS", name="Чужая", is_active=True, is_default_for_currency=True, sort_order=0
        )
        foreign = Wallet.objects.create(
            tenant=other, wallet_type=Wallet.Type.CASH, currency="UZS", opening_balance=0, cash_register=register
        )
        req = self.draft()
        res = self.put(req, {"to_wallet_id": foreign.id})
        self.assertEqual(res.status_code, 400)

    def test_other_user_forbidden(self):
        req = self.draft()
        member = User.objects.create_user(username="cd-requester", password="x", full_name="Рядовой")
        TenantMembership.objects.create(tenant=self.tenant, user=member, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=member, role=TenantUserRole.ROLE_REQUESTER)
        self.client.force_authenticate(member)
        res = self.put(req, {"to_wallet_id": self.safe.id})
        self.assertEqual(res.status_code, 403)

    def test_creator_with_requester_role_allowed(self):
        member = User.objects.create_user(username="cd-requester2", password="x", full_name="Автор")
        TenantMembership.objects.create(tenant=self.tenant, user=member, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=member, role=TenantUserRole.ROLE_REQUESTER)
        req = self.draft(created_by=member)
        self.client.force_authenticate(member)
        res = self.put(req, {"to_wallet_id": self.safe.id})
        self.assertEqual(res.status_code, 200, res.data)

    def test_foreign_tenant_request_404(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        req = self.draft(tenant=other, wallet_ref=None)
        res = self.put(req, {"to_wallet_id": self.safe.id})
        self.assertEqual(res.status_code, 404)

    def test_put_twice_updates(self):
        req = self.draft()
        self.put(req, {"to_wallet_id": self.safe.id})
        res = self.put(req, {"to_wallet_id": self.usd.id, "to_amount": "130"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(CashRegisterTransferTarget.objects.filter(request=req).count(), 1)
        target = CashRegisterTransferTarget.objects.get(request=req)
        self.assertEqual(target.to_wallet_id, self.usd.id)
        self.assertEqual(target.to_amount, Decimal("130.00"))
