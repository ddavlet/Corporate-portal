from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.vendors.models import Vendor
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class VendorApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.cashier = User.objects.create_user(username="cashier1", password="x")
        self.requester = User.objects.create_user(username="req1", password="x")
        for u in (self.admin, self.cashier, self.requester):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN, step=1)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.cashier, role=TenantUserRole.ROLE_CASHIER, step=1)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER, step=1)
        for key in ("vendors", "cash", "requests"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)
        self.host = "acme.example.com"

    def test_create_transfer_requires_inn(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/vendors/",
            {"kind": "transfer", "name": "OOO Test"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)

    def test_transfer_inn_unique_per_tenant(self):
        self.client.force_authenticate(self.admin)
        Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="A",
            inn="123456789",
            created_by=self.admin,
        )
        res = self.client.post(
            "/api/vendors/",
            {"kind": "transfer", "name": "B", "inn": "123456789"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertGreaterEqual(res.status_code, 400)

    def test_cashier_can_create_cash_vendor(self):
        self.client.force_authenticate(self.cashier)
        res = self.client.post(
            "/api/vendors/",
            {"kind": "cash", "name": "Kiosk"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201)
