
from datetime import date, datetime
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.cashier.models import CashRevenue
from apps.modules.clients_debt.models import ClientDebtSnapshot
from apps.modules.requests.models import Approval, Request
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import CashRegister, Wallet

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
        self.requester = User.objects.create_user(username="requester", password="pass12345")
        self.approver = User.objects.create_user(username="approver", password="pass12345")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.other, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.requester, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.approver, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.other, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
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

    @patch("apps.modules.n8n_integration.views.requests.post")
    def test_ai_chat_proxy_generates_session_id_and_forwards_payload(self, mocked_post):
        mocked_response = Mock()
        mocked_response.status_code = 200
        mocked_response.json.return_value = [
            {
                "user_id": self.admin.id,
                "session_id": "existing-session-id",
                "response": "AI says hello",
                "history": {"ai": "old", "user": "old"},
            }
        ]
        mocked_post.return_value = mocked_response

        res = self.client.post(
            "/api/ai-questions/chat/",
            {"question": "Как дела?"},
            format="json",
            **self._headers(self.admin, integration=False),
        )
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        self.assertEqual(payload["response"], "AI says hello")
        self.assertEqual(payload["reponse"], "AI says hello")
        self.assertIn("session_id", payload)
        self.assertEqual(payload["session_id"], "existing-session-id")

        called_args = mocked_post.call_args.args
        called_kwargs = mocked_post.call_args.kwargs
        self.assertTrue(called_args[0].endswith("/n8n/aichat"))
        self.assertEqual(called_kwargs["json"]["user"], self.admin.id)
        self.assertEqual(called_kwargs["json"]["question"], "Как дела?")
        self.assertEqual(len(called_kwargs["json"]["session_id"]), 32)

    def test_vendor_upsert_by_account_no_when_id_missing(self):
        Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="Imported by Account",
            inn="987654321",
            account_number="20208000999999999999",
            created_by=self.admin,
        )
        res = self.client.post(
            self.vendor_url,
            {"kind": Vendor.KIND_TRANSFER, "name": "Renamed Vendor", "account_no": "20208000999999999999"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res.status_code, 200, res.content)
        v = Vendor.objects.get(tenant=self.tenant, account_number="20208000999999999999")
        self.assertEqual(v.name, "Renamed Vendor")

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

    def test_payroll_line_upsert_by_doc_id_and_line_no_without_id(self):
        from apps.modules.payroll.models import PayrollLine

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
        url = f"{self.n8n_prefix}/payroll/lines/"
        body = {
            "doc_id": "DOC-PAY-NATURAL-1",
            "line_no": 3,
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
        line = PayrollLine.objects.get(document__tenant=self.tenant, document__doc_id="DOC-PAY-NATURAL-1", line_no=3)
        first_id = line.id
        self.assertEqual(str(line.sum), "1000.00")

        res2 = self.client.post(
            url,
            {**body, "sum": "1100.00", "employee": "Ivan I."},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        line.refresh_from_db()
        self.assertEqual(line.id, first_id)
        self.assertEqual(str(line.sum), "1100.00")
        self.assertEqual(line.employee, "Ivan I.")

    def test_bank_revenue_upsert_tenant_isolation(self):
        from apps.modules.bank_expenses.models import BankRevenue

        tenant_b = Tenant.objects.create(name="Beta Corp", subdomain="beta", is_active=True)
        admin_b = User.objects.create_user(username="admin_beta", password="pass12345")
        TenantMembership.objects.create(tenant=tenant_b, user=admin_b, is_active=True)
        TenantUserRole.objects.create(tenant=tenant_b, user=admin_b, role=TenantUserRole.ROLE_ADMIN)

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

    def test_bank_expense_resolves_vendor_by_account_no(self):
        vendor = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="Bank Supplier",
            inn="123456789",
            account_number="20208000999999999999",
            created_by=self.admin,
        )
        url = f"{self.n8n_prefix}/bank/expenses/"
        body = {
            "id": 93001,
            "row_no": 1,
            "doc_date": "2026-03-30",
            "process_date": "2026-03-30",
            "doc_no": "BEXP-N8N-1",
            "account_no": "20208000999999999999",
            "debit_turnover": "500.00",
            "payment_purpose": "Оплата поставки",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankExpense.objects.get(pk=93001)
        self.assertEqual(row.vendor_id, vendor.id)

    def test_bank_expense_resolves_vendor_by_account_name(self):
        vendor = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="Vendor by Name",
            inn="123456789",
            account_number="20208000111111111111",
            created_by=self.admin,
        )
        url = f"{self.n8n_prefix}/bank/expenses/"
        body = {
            "id": 93002,
            "row_no": 1,
            "doc_date": "2026-03-30",
            "process_date": "2026-03-30",
            "doc_no": "BEXP-N8N-2",
            "account_name": "Vendor by Name",
            "debit_turnover": "300.00",
            "payment_purpose": "Оплата по названию",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankExpense.objects.get(pk=93002)
        self.assertEqual(row.vendor_id, vendor.id)

    def test_bank_expense_prefers_account_no_when_account_name_is_ambiguous(self):
        vendor_by_account = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="ООО LEMON-SPORT-GROUP",
            inn="308765632",
            account_number="16401000505425326000",
            created_by=self.admin,
        )
        Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="ООО LEMON-SPORT-GROUP",
            inn="308765632",
            account_number="16401000505425326001",
            created_by=self.admin,
        )
        url = f"{self.n8n_prefix}/bank/expenses/"
        body = {
            "id": 93003,
            "row_no": 1,
            "doc_date": "2026-03-30",
            "process_date": "2026-03-30",
            "doc_no": "BEXP-N8N-3",
            "account_name": "ООО LEMON-SPORT-GROUP",
            "account_no": "16401000505425326000",
            "debit_turnover": "1000.00",
            "payment_purpose": "Оплата по счету",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = BankExpense.objects.get(pk=93003)
        self.assertEqual(row.vendor_id, vendor_by_account.id)

    def test_cash_revenue_import_fields_supported(self):
        url = f"{self.n8n_prefix}/cash/revenues/"
        body = {
            "id": 94001,
            "external_id": "1-000004435",
            "date": "2026-03-19T19:00:00.000Z",
            "confirmed": True,
            "direction": "in",
            "organization": "LEMONFIT",
            "unit": "LEMONFIT",
            "employee": "",
            "cash_type": "Наличные",
            "operation": "Взнос на лицевой счет",
            "account": "Основная касса (касса)",
            "counterparty": "Encarnacion Jose",
            "contract": "",
            "total_sum": "20000",
            "comment": "",
            "source_year": 2026,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CashRevenue.objects.get(pk=94001)
        self.assertEqual(row.external_id, "1-000004435")
        self.assertEqual(str(row.total_sum), "20000.00")
        self.assertEqual(row.payload.get("account"), "Основная касса (касса)")
        self.assertEqual(row.payload.get("direction"), "in")
        self.assertEqual(row.payload.get("source_year"), 2026)

    def test_cash_revenue_string_id_maps_to_external_id(self):
        url = f"{self.n8n_prefix}/cash/revenues/"
        body = {
            "id": "1-000004435",
            "date": "2026-03-19T19:00:00.000Z",
            "confirmed": True,
            "direction": "in",
            "organization": "LEMONFIT",
            "unit": "LEMONFIT",
            "total_sum": "20000",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CashRevenue.objects.get(tenant=self.tenant, external_id="1-000004435")
        self.assertEqual(str(row.total_sum), "20000.00")

        res2 = self.client.post(
            url,
            {**body, "total_sum": "21000"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        row.refresh_from_db()
        self.assertEqual(str(row.total_sum), "21000.00")

    def test_cash_revenue_without_id_upserts_by_external_id_source_year(self):
        url = f"{self.n8n_prefix}/cash/revenues/"
        body = {
            "external_id": "1-000004500",
            "source_year": 2026,
            "date": "2026-03-19T19:00:00.000Z",
            "confirmed": True,
            "direction": "in",
            "organization": "LEMONFIT",
            "unit": "LEMONFIT",
            "total_sum": "20000",
            "cash_register_name": "Main cash",
        }
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )

        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)

        res2 = self.client.post(
            url,
            {**body, "total_sum": "21000"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        row = CashRevenue.objects.get(tenant=self.tenant, external_id="1-000004500", source_year=2026)
        self.assertEqual(str(row.total_sum), "21000.00")

    def test_cash_revenue_pk_as_id_and_id_as_external(self):
        url = f"{self.n8n_prefix}/cash/revenues/"
        body = {
            "pk": "95001",
            "id": "1-000009999",
            "date": "2026-03-19T19:00:00.000Z",
            "confirmed": True,
            "direction": "in",
            "total_sum": "30000",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CashRevenue.objects.get(pk=95001)
        self.assertEqual(row.external_id, "1-000009999")

    def test_cash_revenue_prefers_natural_key_when_numeric_id_conflicts(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Сейф (касса)")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        target = CashRevenue.objects.create(
            id=97001,
            tenant=self.tenant,
            external_id="1-000005033",
            source_year=2026,
            revenue_at=datetime(2026, 3, 29, 19, 0, 0),
            currency="UZS",
            total_sum="18000.00",
            wallet=cash_wallet,
            created_by=self.admin,
        )
        other_by_id = CashRevenue.objects.create(
            id=1335922,
            tenant=self.tenant,
            external_id="OTHER-ROW",
            source_year=2026,
            revenue_at=datetime(2026, 3, 28, 19, 0, 0),
            currency="UZS",
            total_sum="999.00",
            wallet=cash_wallet,
            created_by=self.admin,
        )

        url = f"{self.n8n_prefix}/cash/revenues/"
        body = {
            "id": 1335922,
            "external_id": "1-000005033",
            "date": "2026-03-29T19:00:00.000Z",
            "confirmed": True,
            "direction": "in",
            "organization": "LEMONFIT",
            "unit": "LEMONFIT",
            "employee": "Сумина Наталья",
            "cash_type": "Наличные",
            "operation": "Поступление розничной выручки из операционной кассы",
            "counterparty": "",
            "contract": "",
            "total_sum": "18786000",
            "comment": "",
            "source_year": 2026,
            "currency": "UZS",
            "cash_register_name": "Сейф (касса)",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200, res.content)

        target.refresh_from_db()
        self.assertEqual(str(target.total_sum), "18786000.00")
        self.assertEqual(target.external_id, "1-000005033")

        other_by_id.refresh_from_db()
        self.assertEqual(other_by_id.external_id, "OTHER-ROW")
        self.assertEqual(str(other_by_id.total_sum), "999.00")

    def test_cash_revenue_can_bind_wallet_by_cash_register_name(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        url = f"{self.n8n_prefix}/cash/revenues/"
        body = {
            "id": 95011,
            "date": "2026-03-19T19:00:00.000Z",
            "confirmed": True,
            "total_sum": "30000",
            "currency": "UZS",
            "cash_register_name": "Main cash",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CashRevenue.objects.get(pk=95011)
        self.assertEqual(row.wallet_id, cash_wallet.id)

    def test_request_upsert_with_client_id(self):
        url = f"{self.n8n_prefix}/requests/"
        body = {
            "id": 5010,
            "title": "Imported request",
            "description": "from n8n",
            "amount": "1200.00",
            "currency": "UZS",
            "payment_type": "Наличные",
            "urgency": "Обычно",
            "requester": self.requester.id,
            "status": "DRAFT",
            "billing_date": "2026-04-01",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(pk=5010)
        self.assertEqual(req.tenant_id, self.tenant.id)
        self.assertEqual(req.created_by_id, 1)
        self.assertEqual(req.requester_id, self.requester.id)

        res2 = self.client.post(
            url,
            {**body, "title": "Imported request updated"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        req.refresh_from_db()
        self.assertEqual(req.title, "Imported request updated")

    def test_requests_amortization_endpoint_requires_admin(self):
        url = f"{self.n8n_prefix}/requests/amortization/"
        self.client.force_authenticate(self.other)
        res = self.client.get(url, **self._headers(self.other))
        self.assertEqual(res.status_code, 403)

    def test_requests_amortization_endpoint_returns_only_amortized_by_default(self):
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Amortized request",
            description="",
            amount="100.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 4, 1),
            amortization_months=3,
            amortization_start_date=date(2026, 4, 1),
            status=Request.STATUS_DRAFT,
        )
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Plain request",
            description="",
            amount="50.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 4, 1),
            amortization_months=1,
            amortization_start_date=date(2026, 4, 1),
            status=Request.STATUS_DRAFT,
        )
        url = f"{self.n8n_prefix}/requests/amortization/"
        res = self.client.get(url, **self._headers(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["count"], 1)
        item = res.data["results"][0]
        self.assertTrue(item["is_amortized"])
        self.assertEqual(item["amortization_months"], 3)
        self.assertEqual(len(item["amortization_schedule"]), 3)

    def test_requests_amortization_endpoint_can_return_all(self):
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Plain request",
            description="",
            amount="50.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 4, 1),
            amortization_months=1,
            amortization_start_date=date(2026, 4, 1),
            status=Request.STATUS_DRAFT,
        )
        url = f"{self.n8n_prefix}/requests/amortization/?amortized_only=0&request_id={req.id}"
        res = self.client.get(url, **self._headers(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["id"], req.id)
        self.assertFalse(res.data["results"][0]["is_amortized"])

    def test_cash_expense_can_bind_wallet_by_cash_register_name(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        url = f"{self.n8n_prefix}/cash/expenses/"
        body = {
            "id": 96011,
            "external_id": "CASH-NAME-1",
            "confirmed": True,
            "title": "By cash name",
            "amount": "1200.00",
            "currency": "UZS",
            "expense_at": "2026-04-01T10:00:00.000Z",
            "cash_register_name": "Main cash",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CashExpense.objects.get(pk=96011)
        self.assertEqual(row.wallet_id, cash_wallet.id)

    def test_cash_expense_validation_error_has_reason_and_location(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        url = f"{self.n8n_prefix}/cash/expenses/"
        body = {
            "id": 96012,
            "external_id": "CASH-NAME-2",
            "confirmed": True,
            "title": "Broken payload",
            "amount": "1200.00",
            "currency": "UZS",
            "cash_register_name": "Main cash",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.data.get("error_type"), "validation_error")
        self.assertEqual(res.data.get("error_location"), url)
        self.assertEqual(res.data.get("detail"), "Validation failed.")
        self.assertIn("errors", res.data)
        self.assertIn("expense_at", res.data["errors"])

    def test_cash_expense_batch_error_has_failed_item_and_rollback(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        url = f"{self.n8n_prefix}/cash/expenses/batch/"
        body = [
            {
                "id": 96013,
                "external_id": "CASH-BATCH-1",
                "confirmed": True,
                "title": "Good item",
                "amount": "1200.00",
                "currency": "UZS",
                "expense_at": "2026-04-01T10:00:00.000Z",
                "cash_register_name": "Main cash",
            },
            {
                "id": 96014,
                "external_id": "CASH-BATCH-2",
                "confirmed": True,
                "title": "Bad item",
                "amount": "1300.00",
                "currency": "UZS",
                "cash_register_name": "Main cash",
            },
        ]
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.data.get("error_type"), "batch_item_failed")
        self.assertEqual(res.data.get("error_location"), "batch")
        self.assertEqual(res.data.get("failed_index"), 1)
        self.assertEqual(res.data.get("failed_item", {}).get("external_id"), "CASH-BATCH-2")
        self.assertEqual(res.data.get("failed_item_summary", {}).get("external_id"), "CASH-BATCH-2")
        self.assertIn("expense_at", res.data.get("failed_data", {}))
        self.assertFalse(CashExpense.objects.filter(pk=96013).exists())

    def test_cash_expense_without_id_upserts_by_external_id_and_expense_year(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        url = f"{self.n8n_prefix}/cash/expenses/"
        body = {
            "external_id": "1-000000329",
            "title": "Зарплата по ведомости",
            "amount": "8536000",
            "currency": "UZS",
            "expense_at": "2026-04-09T00:00:00.000+05:00",
            "note": "рецепция",
            "confirmed": True,
            "cash_register_name": "Main cash",
            "payload": {"id": "1-000000329"},
        }

        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CashExpense.objects.get(tenant=self.tenant, external_id="1-000000329", expense_year=2026)
        self.assertEqual(str(row.amount), "8536000.00")

        res2 = self.client.post(
            url,
            {**body, "amount": "8537000", "note": "обновление"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        row.refresh_from_db()
        self.assertEqual(str(row.amount), "8537000.00")
        self.assertEqual(row.note, "обновление")

    def test_cash_expense_prefers_natural_key_when_numeric_id_conflicts(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        target = CashExpense.objects.create(
            id=98001,
            tenant=self.tenant,
            external_id="1-000000329",
            confirmed=True,
            title="Зарплата по ведомости",
            amount="1000.00",
            currency="UZS",
            expense_at=datetime(2026, 4, 9, 0, 0, 0),
            expense_year=2026,
            expense_month=4,
            expense_day=9,
            note="before",
            wallet=cash_wallet,
            created_by=self.admin,
        )
        other_by_id = CashExpense.objects.create(
            id=1335922,
            tenant=self.tenant,
            external_id="OTHER-EXP-1",
            confirmed=True,
            title="Other row",
            amount="999.00",
            currency="UZS",
            expense_at=datetime(2026, 4, 8, 0, 0, 0),
            expense_year=2026,
            expense_month=4,
            expense_day=8,
            note="untouched",
            wallet=cash_wallet,
            created_by=self.admin,
        )

        url = f"{self.n8n_prefix}/cash/expenses/"
        body = {
            "id": 1335922,
            "external_id": "1-000000329",
            "title": "Зарплата по ведомости",
            "amount": "8537000",
            "currency": "UZS",
            "expense_at": "2026-04-09T00:00:00.000+05:00",
            "note": "обновление",
            "confirmed": True,
            "cash_register_name": "Main cash",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200, res.content)

        target.refresh_from_db()
        self.assertEqual(str(target.amount), "8537000.00")
        self.assertEqual(target.note, "обновление")

        other_by_id.refresh_from_db()
        self.assertEqual(other_by_id.external_id, "OTHER-EXP-1")
        self.assertEqual(str(other_by_id.amount), "999.00")

    def test_request_upsert_resolves_expense_ref_id_for_cash(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        cash_expense = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="CASH-1",
            confirmed=True,
            title="Imported expense",
            amount="1200.00",
            currency="UZS",
            expense_at=datetime(2026, 4, 1, 10, 0, 0),
            expense_year=2026,
            expense_month=4,
            expense_day=1,
            created_by=self.admin,
            wallet=cash_wallet,
        )
        url = f"{self.n8n_prefix}/requests/"
        body = {
            "id": 5011,
            "title": "Imported request",
            "description": "from n8n",
            "amount": "1200.00",
            "currency": "UZS",
            "payment_type": "Наличные",
            "urgency": "Обычно",
            "requester": self.requester.id,
            "status": "DRAFT",
            "billing_date": "2026-04-01",
            "expense_id": "CASH-1",
            "expense_year": 2026,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(pk=5011)
        self.assertEqual(req.expense_ref_id, cash_expense.id)

    def test_request_upsert_allows_two_requests_same_resolved_cash_expense(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Dup cash")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        cash_expense = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="CASH-DUP-1",
            confirmed=True,
            title="Shared expense",
            amount="900.00",
            currency="UZS",
            expense_at=datetime(2026, 4, 2, 11, 0, 0),
            expense_year=2026,
            expense_month=4,
            expense_day=2,
            created_by=self.admin,
            wallet=cash_wallet,
        )
        url = f"{self.n8n_prefix}/requests/"
        body_a = {
            "id": 5020,
            "title": "First request",
            "description": "from n8n",
            "amount": "900.00",
            "currency": "UZS",
            "payment_type": "Наличные",
            "urgency": "Обычно",
            "requester": self.requester.id,
            "status": "DRAFT",
            "billing_date": "2026-04-02",
            "expense_id": "CASH-DUP-1",
            "expense_year": 2026,
        }
        res1 = self.client.post(url, body_a, format="json", **self._headers(self.admin))
        self.assertEqual(res1.status_code, 201, res1.content)
        req1 = Request.objects.get(pk=5020)
        self.assertEqual(req1.expense_ref_id, cash_expense.id)

        body_b = {
            **body_a,
            "id": 5021,
            "title": "Second request",
        }
        res2 = self.client.post(url, body_b, format="json", **self._headers(self.admin))
        self.assertEqual(res2.status_code, 201, res2.content)
        req2 = Request.objects.get(pk=5021)
        self.assertEqual(req2.expense_ref_id, cash_expense.id)

    def test_request_upsert_keeps_expense_id_when_expense_not_yet_imported(self):
        url = f"{self.n8n_prefix}/requests/"
        body = {
            "id": 5012,
            "title": "Pending link",
            "description": "",
            "amount": "500.00",
            "currency": "UZS",
            "payment_type": "Наличные",
            "urgency": "Обычно",
            "requester": self.requester.id,
            "status": "DRAFT",
            "billing_date": "2026-04-01",
            "expense_id": "NOT-IMPORTED-YET",
            "expense_year": 2026,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(pk=5012)
        self.assertEqual(req.expense_id, "NOT-IMPORTED-YET")
        self.assertIsNone(req.expense_ref_id)

    def test_clients_debt_upsert_with_client_id(self):
        url = f"{self.n8n_prefix}/clients-debt/"
        body = {
            "id": 98001,
            "date": "2026-04-10T00:00:00.000+05:00",
            "doc_type": "client_debt_total",
            "organization": "LEMONFIT",
            "client": "Тураев Артур Таштемирович",
            "client_id": "000000006",
            "debt_sum": "8000",
            "quantity": "0",
            "cert_discount": "0",
            "payload": {"source": "n8n"},
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = ClientDebtSnapshot.objects.get(pk=98001)
        self.assertEqual(row.tenant_id, self.tenant.id)
        self.assertEqual(row.created_by_id, 1)
        self.assertEqual(row.client_id, "000000006")

        res2 = self.client.post(
            url,
            {**body, "debt_sum": "9000"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        row.refresh_from_db()
        self.assertEqual(str(row.debt_sum), "9000.00")

    def test_clients_debt_upsert_by_date_and_client_without_id(self):
        url = f"{self.n8n_prefix}/clients-debt/"
        body = {
            "date": "2026-04-10T00:00:00.000+05:00",
            "doc_type": "client_debt_total",
            "organization": "LEMONFIT",
            "client": "Тураев Артур Таштемирович",
            "client_id": "000000006",
            "debt_sum": "8000",
            "quantity": "0",
            "cert_discount": "0",
            "payload": {"source": "n8n"},
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = ClientDebtSnapshot.objects.get(
            tenant=self.tenant,
            client="Тураев Артур Таштемирович",
            client_id="000000006",
        )
        first_id = row.id
        self.assertEqual(str(row.debt_sum), "8000.00")

        res2 = self.client.post(
            url,
            {**body, "debt_sum": "9000"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        row.refresh_from_db()
        self.assertEqual(row.id, first_id)
        self.assertEqual(str(row.debt_sum), "9000.00")

    def test_approval_upsert_with_client_id(self):
        req = Request.objects.create(
            id=6010,
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Seed request",
            billing_date=date(2026, 4, 1),
        )
        url = f"{self.n8n_prefix}/approvals/"
        body = {
            "id": 7010,
            "request": req.id,
            "approver_user": self.approver.id,
            "approver_tg_id": 555001,
            "step": 1,
            "step_type": "serial",
            "decision": "pending",
            "message_sent": True,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        appr = Approval.objects.get(pk=7010)
        self.assertEqual(appr.request_id, req.id)
        self.assertEqual(appr.approver_user_id, self.approver.id)
        self.assertEqual(appr.approver_tg_id, 555001)

        res2 = self.client.post(
            url,
            {**body, "decision": "approved"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        appr.refresh_from_db()
        self.assertEqual(appr.decision, "approved")

