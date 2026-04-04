from datetime import date

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.bank_expenses.models import BankRevenue
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class BankRevenueApiTenantIsolationTests(APITestCase):
    def setUp(self):
        su, _ = User.objects.update_or_create(
            pk=1,
            defaults={"username": "n8n_system"},
        )
        if not su.has_usable_password():
            su.set_unusable_password()
            su.save(update_fields=["password"])

        self.tenant_a = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.tenant_b = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True)
        self.admin_a = User.objects.create_user(username="admin_a", password="x")
        self.admin_b = User.objects.create_user(username="admin_b", password="x")
        for t, u in (
            (self.tenant_a, self.admin_a),
            (self.tenant_b, self.admin_b),
        ):
            TenantMembership.objects.create(tenant=t, user=u, is_active=True)
            TenantUserRole.objects.create(tenant=t, user=u, role=TenantUserRole.ROLE_ADMIN, step=1)
            TenantModuleConfig.objects.create(tenant=t, module_key="bank", is_enabled=True)

        d = date(2026, 4, 1)
        BankRevenue.objects.create(
            tenant=self.tenant_a,
            created_by=su,
            row_no=1,
            doc_date=d,
            process_date=d,
            doc_no="R-A",
            account_name="A",
            inn="100000000",
            account_no="20208000111111111111",
            mfo="01001",
            kredit_turnover="10.00",
            payment_purpose="p-a",
        )
        BankRevenue.objects.create(
            tenant=self.tenant_b,
            created_by=su,
            row_no=1,
            doc_date=d,
            process_date=d,
            doc_no="R-B",
            account_name="B",
            inn="200000000",
            account_no="20208000222222222222",
            mfo="01001",
            kredit_turnover="20.00",
            payment_purpose="p-b",
        )

    def _headers(self, user, host):
        token = str(RefreshToken.for_user(user).access_token)
        return {
            "HTTP_HOST": host,
            "HTTP_AUTHORIZATION": f"Bearer {token}",
        }

    def test_list_revenues_scoped_to_tenant(self):
        res_a = self.client.get("/api/bank/revenues/", **self._headers(self.admin_a, "acme.example.com"))
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.json()
        results_a = data_a if isinstance(data_a, list) else data_a.get("results", data_a)
        doc_nos_a = {r["doc_no"] for r in results_a}
        self.assertEqual(doc_nos_a, {"R-A"})

        res_b = self.client.get("/api/bank/revenues/", **self._headers(self.admin_b, "beta.example.com"))
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.json()
        results_b = data_b if isinstance(data_b, list) else data_b.get("results", data_b)
        doc_nos_b = {r["doc_no"] for r in results_b}
        self.assertEqual(doc_nos_b, {"R-B"})
