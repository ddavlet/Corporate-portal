from datetime import date

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.bank_expenses.models import BankExpense
from apps.modules.wallets.resolution import get_or_create_bank_wallet
from apps.modules.requests.models import Request, RequestApprovalConfig, RequestApprovalPaymentTypeConfig
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
            TenantUserRole.objects.create(tenant=t, user=u, role=TenantUserRole.ROLE_ADMIN)
            TenantModuleConfig.objects.create(tenant=t, module_key="bank", is_enabled=True)

        d = date(2026, 4, 1)
        wa = get_or_create_bank_wallet(tenant=self.tenant_a)
        wb = get_or_create_bank_wallet(tenant=self.tenant_b)
        BankRevenue.objects.create(
            tenant=self.tenant_a,
            created_by=su,
            wallet=wa,
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
            wallet=wb,
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


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class BankExpenseRequestRequiredApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="AcmeBank", subdomain="acmebank", is_active=True)
        self.admin = User.objects.create_user(username="bank_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="bank", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.wallet = get_or_create_bank_wallet(tenant=self.tenant)
        self.appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        self.pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=self.appr_cfg,
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            is_enabled=True,
        )

    def _headers(self):
        token = str(RefreshToken.for_user(self.admin).access_token)
        return {
            "HTTP_HOST": "acmebank.example.com",
            "HTTP_AUTHORIZATION": f"Bearer {token}",
        }

    def test_request_highlight_contract_scenarios(self):
        d = date(2026, 4, 1)
        required_missing = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            wallet=self.wallet,
            row_no=1,
            doc_date=d,
            process_date=d,
            expense_year=2026,
            expense_month=4,
            expense_day=1,
            doc_no="DOC-REQ-MISS",
            debit_turnover="10.00",
            payment_purpose="P1",
        )
        required_paid = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            wallet=self.wallet,
            row_no=2,
            doc_date=d,
            process_date=d,
            expense_year=2026,
            expense_month=4,
            expense_day=1,
            doc_no="DOC-REQ-PAID",
            debit_turnover="20.00",
            payment_purpose="P2",
        )
        optional_missing = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            wallet=self.wallet,
            row_no=3,
            doc_date=d,
            process_date=d,
            expense_year=2026,
            expense_month=4,
            expense_day=1,
            doc_no="DOC-OPT-MISS",
            debit_turnover="30.00",
            payment_purpose="P3",
        )
        self.pt_cfg.request_not_required_rules = [{"field": "doc_no", "operator": "eq", "value": "DOC-OPT-MISS"}]
        self.pt_cfg.save(update_fields=["request_not_required_rules"])
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Paid",
            amount="20.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=d,
            status=Request.STATUS_PAYED,
            expense_ref_id=required_paid.id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            expense_id=required_paid.doc_no,
            expense_year=required_paid.expense_year,
        )

        res = self.client.get("/api/bank/expenses/", **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        by_id = {row["id"]: row for row in rows}
        self.assertTrue(by_id[required_missing.id]["request_required"])
        self.assertFalse(by_id[required_missing.id]["has_paid_request"])
        self.assertTrue(by_id[required_paid.id]["request_required"])
        self.assertTrue(by_id[required_paid.id]["has_paid_request"])
        self.assertFalse(by_id[optional_missing.id]["request_required"])
        self.assertFalse(by_id[optional_missing.id]["has_paid_request"])
