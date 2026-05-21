from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.contracts.models import Contract
from apps.modules.vendors.models import Vendor
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


class ContractUniqueConstraintTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="cuser", password="x")
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_CASH, name="Vendor A", created_by=self.user
        )

    def test_duplicate_tenant_vendor_number_date_from_raises_integrity_error(self):
        Contract.objects.create(
            tenant=self.tenant,
            vendor=self.vendor,
            contract_number="NN-1",
            date_from=date(2026, 1, 1),
            contract_amount=Decimal("100.00"),
            currency="UZS",
            contract_status=Contract.STATUS_ACCEPTED,
            created_by=self.user,
        )
        with self.assertRaises(IntegrityError):
            Contract.objects.create(
                tenant=self.tenant,
                vendor=self.vendor,
                contract_number="NN-1",
                date_from=date(2026, 1, 1),
                contract_amount=Decimal("200.00"),
                currency="UZS",
                contract_status=Contract.STATUS_ACCEPTED,
                created_by=self.user,
            )


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ContractApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="cadmin", password="x")
        self.requester = User.objects.create_user(username="creq", password="x")
        for u in (self.admin, self.requester):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="vendors", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="contracts", is_enabled=True)
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_CASH, name="Vendor B", created_by=self.admin
        )
        self.host = "acme.example.com"

    def _headers(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return {"HTTP_HOST": self.host, "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_admin_duplicate_contract_returns_400(self):
        def _payload():
            return {
                "vendor": self.vendor.id,
                "contract_number": "DUP-1",
                "date_from": "2026-02-01",
                "contract_amount": "10.00",
                "currency": "UZS",
                "contract_status": Contract.STATUS_ACCEPTED,
                "contract_file": SimpleUploadedFile("c.pdf", b"%PDF-1.4", content_type="application/pdf"),
            }
        r1 = self.client.post("/api/contracts/", _payload(), format="multipart", **self._headers(self.admin))
        self.assertEqual(r1.status_code, 201, r1.content)
        r2 = self.client.post("/api/contracts/", _payload(), format="multipart", **self._headers(self.admin))
        self.assertEqual(r2.status_code, 400, r2.content)

    def test_create_without_file_returns_400(self):
        payload = {
            "vendor": self.vendor.id,
            "contract_number": "NF-1",
            "date_from": "2026-02-01",
            "contract_amount": "10.00",
            "currency": "UZS",
            "contract_status": Contract.STATUS_ACCEPTED,
        }
        res = self.client.post("/api/contracts/", payload, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("contract_file", res.data)

    def test_requester_can_list_but_not_create(self):
        Contract.objects.create(
            tenant=self.tenant,
            vendor=self.vendor,
            contract_number="R-1",
            date_from=date(2026, 3, 1),
            contract_amount=Decimal("1.00"),
            currency="UZS",
            contract_status=Contract.STATUS_ACCEPTED,
            created_by=self.admin,
        )
        lst = self.client.get("/api/contracts/", **self._headers(self.requester))
        self.assertEqual(lst.status_code, 200, lst.content)
        self.assertGreaterEqual(len(lst.data), 1)
        cre = self.client.post(
            "/api/contracts/",
            {
                "vendor": self.vendor.id,
                "contract_number": "R-NEW",
                "date_from": "2026-03-02",
                "contract_amount": "5.00",
                "currency": "UZS",
                "contract_status": Contract.STATUS_ACCEPTED,
            },
            format="json",
            **self._headers(self.requester),
        )
        self.assertEqual(cre.status_code, 403, cre.content)
