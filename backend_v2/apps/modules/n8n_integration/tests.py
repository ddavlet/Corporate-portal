
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.vendors.models import Vendor

User = get_user_model()


@override_settings(
    BASE_DOMAIN="example.com",
    N8N_INTEGRATION_TOKEN="integ-test-secret",
    ALLOWED_HOSTS=["acme.example.com", "beta.example.com", "testserver"],
)
class N8nIntegrationAuthTests(APITestCase):
    def setUp(self):
        su, _ = User.objects.update_or_create(
            pk=1,
            defaults={"username": "n8n_system"},
        )
        if not su.has_usable_password():
            su.set_unusable_password()
            su.save(update_fields=["password"])

        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="pass12345")
        self.other = User.objects.create_user(username="member", password="pass12345")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.other, is_active=True)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN, step=1
        )
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.other, role=TenantUserRole.ROLE_REQUESTER, step=1
        )
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="vendors", is_enabled=True)

        self.n8n_prefix = settings.N8N_INTEGRATION_URL_PREFIX.rstrip("/")
        self.vendor_url = f"{self.n8n_prefix}/vendors/"

    def _headers(self, user=None, integration=True, host="acme.example.com"):
        h = {
            "HTTP_HOST": host,
        }
        if integration:
            h["HTTP_X_N8N_INTEGRATION_TOKEN"] = "integ-test-secret"
        if user is not None:
            access = str(RefreshToken.for_user(user).access_token)
            h["HTTP_AUTHORIZATION"] = f"Bearer {access}"
        return h

    def test_missing_integration_token_401(self):
        res = self.client.post(
            self.vendor_url,
            {"id": 1, "kind": Vendor.KIND_CASH, "name": "V"},
            format="json",
            **self._headers(self.admin, integration=False),
        )
        self.assertEqual(res.status_code, 401)

    def test_missing_jwt_401(self):
        res = self.client.post(
            self.vendor_url,
            {"id": 1, "kind": Vendor.KIND_CASH, "name": "V"},
            format="json",
            HTTP_HOST="acme.example.com",
            HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 401)

    def test_non_admin_403(self):
        res = self.client.post(
            self.vendor_url,
            {"id": 1, "kind": Vendor.KIND_CASH, "name": "V"},
            format="json",
            **self._headers(self.other),
        )
        self.assertEqual(res.status_code, 403)

    def test_upsert_vendor_created_by_system_user(self):
        res = self.client.post(
            self.vendor_url,
            {"id": 42, "kind": Vendor.KIND_CASH, "name": "Imported"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res.status_code, 201, res.content)
        v = Vendor.objects.get(pk=42)
        self.assertEqual(v.tenant_id, self.tenant.id)
        self.assertEqual(v.created_by_id, 1)

        res2 = self.client.post(
            self.vendor_url,
            {"id": 42, "kind": Vendor.KIND_CASH, "name": "Updated"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200)
        v.refresh_from_db()
        self.assertEqual(v.name, "Updated")

    def test_payroll_line_upsert(self):
        from apps.modules.payroll.models import PayrollLine

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
        url = f"{self.n8n_prefix}/payroll/lines/"
        body = {
            "id": 1001,
            "doc_id": "DOC-PAY-1",
            "line_no": 1,
            "employee": "Ivan",
            "item": "Зарплата",
            "description": "",
            "sum": "1000.00",
            "days_plan": 22,
            "days_fact": 20,
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "approval": False,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        line = PayrollLine.objects.get(pk=1001)
        self.assertEqual(line.document.doc_id, "DOC-PAY-1")
        self.assertEqual(line.document.tenant_id, self.tenant.id)

        res2 = self.client.post(
            url,
            {**body, "sum": "1100.00", "employee": "Ivan I."},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200)
        line.refresh_from_db()
        self.assertEqual(str(line.sum), "1100.00")
        self.assertEqual(line.employee, "Ivan I.")

    def test_bank_revenue_upsert_tenant_isolation(self):
        from apps.modules.bank_expenses.models import BankRevenue

        tenant_b = Tenant.objects.create(name="Beta Corp", subdomain="beta", is_active=True)
        admin_b = User.objects.create_user(username="admin_beta", password="pass12345")
        TenantMembership.objects.create(tenant=tenant_b, user=admin_b, is_active=True)
        TenantUserRole.objects.create(
            tenant=tenant_b, user=admin_b, role=TenantUserRole.ROLE_ADMIN, step=1
        )

        url = f"{self.n8n_prefix}/bank/revenues/"
        body = {
            "id": 92001,
            "row_no": 1,
            "doc_date": "2026-03-30",
            "process_date": "2026-03-30",
            "doc_no": "BREV-N8N-1",
            "account_name": "Плательщик",
            "inn": "111222333",
            "account_no": "20208000999999999999",
            "mfo": "01001",
            "kredit_turnover": "500.00",
            "payment_purpose": "Поступление",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankRevenue.objects.get(pk=92001)
        self.assertEqual(row.tenant_id, self.tenant.id)

        res_conflict = self.client.post(
            url, body, format="json", **self._headers(admin_b, host="beta.example.com")
        )
        self.assertEqual(res_conflict.status_code, 400)
        self.assertIn("id", res_conflict.json())

        res2 = self.client.post(
            url,
            {**body, "kredit_turnover": "600.00", "payment_purpose": "Поступление 2"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(str(row.kredit_turnover), "600.00")

