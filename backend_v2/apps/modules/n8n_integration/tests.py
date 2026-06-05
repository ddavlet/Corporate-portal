
from datetime import date, datetime
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.cashier.models import CashExpense
from apps.modules.cashier.models import CashRevenue
from apps.modules.corporate_card.models import CardRevenue
from apps.modules.clients_debt.models import ClientDebtSnapshot
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepConfig,
    RequestApprovalStepApproverConfig,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.requests.services import list_payment_purposes_by_payment_type
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import CashRegister, Wallet
from apps.modules.wallets.resolution import (
    get_or_create_bank_wallet,
    get_or_create_cash_wallet,
    get_or_create_corporate_wallet,
)

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
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type=Request.PAYMENT_TYPE_CASH, is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)

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

    def test_upsert_works_without_jwt(self):
        res = self.client.post(
            self.vendor_url,
            {"id": 1, "kind": Vendor.KIND_CASH, "name": "V"},
            format="json",
            HTTP_HOST="acme.example.com",
            HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 201, res.content)

    def test_vendors_list_returns_id_and_name_grouped_by_payment_type(self):
        cash_vendor = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_CASH,
            name="Cash Vendor",
            created_by=self.admin,
        )
        transfer_vendor = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="Transfer Vendor",
            created_by=self.admin,
        )
        url = f"{self.n8n_prefix}/vendors-list/"
        res = self.client.get(
            url,
            HTTP_HOST="acme.example.com",
            HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(
            data[Request.PAYMENT_TYPE_CASH],
            [{"id": cash_vendor.id, "name": "Cash Vendor"}],
        )
        transfer_row = {"id": transfer_vendor.id, "name": "Transfer Vendor"}
        self.assertEqual(data[Request.PAYMENT_TYPE_TRANSFER], [transfer_row])
        self.assertEqual(data[Request.PAYMENT_TYPE_TOPUP], [transfer_row])
        self.assertEqual(data[Request.PAYMENT_TYPE_CARD], [transfer_row])

    def test_vendors_list_requires_integration_token(self):
        url = f"{self.n8n_prefix}/vendors-list/"
        res = self.client.get(url, HTTP_HOST="acme.example.com")
        self.assertEqual(res.status_code, 401)

    def test_payment_purposes_list_uses_form_config_and_request_history(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        cash_pt = RequestFormPaymentTypeConfig.objects.create(
            config=cfg,
            payment_type=Request.PAYMENT_TYPE_CASH,
            is_enabled=True,
        )
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=cash_pt,
            name="Configured purpose",
            category="Admin",
            is_active=True,
        )
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            payment_type=Request.PAYMENT_TYPE_CASH,
            payment_purpose="Historical purpose",
            billing_date=date(2026, 1, 1),
        )
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            payment_purpose="Transfer purpose",
            billing_date=date(2026, 1, 1),
        )

        url = f"{self.n8n_prefix}/payment-purposes/"
        res = self.client.get(
            url,
            HTTP_HOST="acme.example.com",
            HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(
            data[Request.PAYMENT_TYPE_CASH],
            ["Configured purpose", "Historical purpose"],
        )
        self.assertEqual(data[Request.PAYMENT_TYPE_TRANSFER], ["Transfer purpose"])
        self.assertEqual(data[Request.PAYMENT_TYPE_TOPUP], [])
        self.assertEqual(data[Request.PAYMENT_TYPE_CARD], [])

        service_data = list_payment_purposes_by_payment_type(tenant_id=self.tenant.id)
        self.assertEqual(service_data, data)

    def test_payment_purposes_list_requires_integration_token(self):
        url = f"{self.n8n_prefix}/payment-purposes/"
        res = self.client.get(url, HTTP_HOST="acme.example.com")
        self.assertEqual(res.status_code, 401)

    def test_wallet_balances_without_jwt(self):
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="bank", is_enabled=True)
        cash_wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        bank_wallet = get_or_create_bank_wallet(tenant=self.tenant)
        url = f"{self.n8n_prefix}/wallet-balances/"
        res = self.client.get(
            url,
            HTTP_HOST="acme.example.com",
            HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertIn("cash", data)
        self.assertIn("bank", data)
        self.assertIn("corporate_card", data)
        self.assertTrue(any(row["wallet_id"] == cash_wallet.id for row in data["cash"]))
        self.assertTrue(any(row["wallet_id"] == bank_wallet.id for row in data["bank"]))
        self.assertEqual(data["corporate_card"], [])

    def test_wallet_balances_channel_filter(self):
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        cash_wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        url = f"{self.n8n_prefix}/wallet-balances/?channel=cash"
        res = self.client.get(
            url,
            HTTP_HOST="acme.example.com",
            HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 200, res.content)
        rows = res.json()
        self.assertIsInstance(rows, list)
        self.assertTrue(any(row["wallet_id"] == cash_wallet.id for row in rows))

    def test_wallet_balances_requires_integration_token(self):
        url = f"{self.n8n_prefix}/wallet-balances/"
        res = self.client.get(url, HTTP_HOST="acme.example.com")
        self.assertEqual(res.status_code, 401)

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

    @patch("apps.modules.n8n_integration.views._n8n_session.post")
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
            # Use a different INN to avoid DB-level uniqueness conflicts in CI databases
            # that still enforce tenant+inn uniqueness for transfer vendors.
            inn="308765633",
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

    def test_bank_expense_upsert_relinks_matching_transfer_request(self):
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Bank relink request",
            description="",
            amount="500.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 30),
            expense_id="BEXP-REL-1",
            expense_year=2026,
            status=Request.STATUS_PAYED,
        )
        url = f"{self.n8n_prefix}/bank/expenses/"
        body = {
            "id": 93010,
            "row_no": 1,
            "doc_date": "2026-03-30",
            "process_date": "2026-03-30",
            "doc_no": "BEXP-REL-1",
            "account_no": "20208000999999999999",
            "debit_turnover": "500.00",
            "payment_purpose": "Оплата поставки",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)
        self.assertEqual(req.expense_ref_id, 93010)

    def test_bank_expense_upsert_does_not_relink_when_amount_mismatch(self):
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Bank relink amount mismatch",
            description="",
            amount="500.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 30),
            expense_id="BEXP-REL-AMT",
            expense_year=2026,
            status=Request.STATUS_PAYED,
        )
        url = f"{self.n8n_prefix}/bank/expenses/"
        body = {
            "id": 93011,
            "row_no": 1,
            "doc_date": "2026-03-30",
            "process_date": "2026-03-30",
            "doc_no": "BEXP-REL-AMT",
            "account_no": "20208000999999999999",
            "debit_turnover": "999.00",
            "payment_purpose": "Другая сумма",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    @patch("apps.modules.n8n_integration.views._relink_requests_to_bank_expenses")
    def test_bank_expense_batch_runs_relink_once(self, relink_mock):
        url = f"{self.n8n_prefix}/bank/expenses/batch/"
        body = [
            {
                "id": 93020,
                "row_no": 1,
                "doc_date": "2026-03-30",
                "process_date": "2026-03-30",
                "doc_no": "BEXP-BATCH-1",
                "account_no": "20208000999999999991",
                "debit_turnover": "500.00",
                "payment_purpose": "Оплата 1",
            },
            {
                "id": 93021,
                "row_no": 2,
                "doc_date": "2026-03-30",
                "process_date": "2026-03-30",
                "doc_no": "BEXP-BATCH-2",
                "account_no": "20208000999999999992",
                "debit_turnover": "600.00",
                "payment_purpose": "Оплата 2",
            },
        ]
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(relink_mock.call_count, 1)

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

    def test_card_revenue_import_minimal_fields(self):
        get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        url = f"{self.n8n_prefix}/corporate-card/revenues/"
        body = {
            "date": "2026-03-19T19:00:00.000Z",
            "total_sum": "20000",
            "currency": "UZS",
            "operation": "Возврат по карте",
            "counterparty": "Encarnacion Jose",
            "external_id": "1-000004435",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        payload = res.json()
        self.assertNotIn("amount", payload)
        self.assertNotIn("note", payload)
        self.assertNotIn("title", payload)
        self.assertEqual(payload.get("total_sum"), "20000.00")
        row = CardRevenue.objects.get(tenant=self.tenant, external_id="1-000004435")
        self.assertEqual(str(row.total_sum), "20000.00")
        self.assertIsNotNone(row.wallet_id)

    def test_card_revenue_import_legacy_fields_go_to_payload(self):
        get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        url = f"{self.n8n_prefix}/corporate-card/revenues/"
        body = {
            "date": "2026-03-19T19:00:00.000Z",
            "total_sum": "20000",
            "direction": "in",
            "organization": "LEMONFIT",
            "unit": "LEMONFIT",
            "employee": "John",
            "cash_type": "Карта",
            "account": "Corp card",
            "source_year": 2026,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CardRevenue.objects.latest("id")
        self.assertEqual(row.payload.get("direction"), "in")
        self.assertEqual(row.payload.get("organization"), "LEMONFIT")
        self.assertEqual(row.payload.get("source_year"), 2026)

    def test_card_revenue_import_amount_and_note_aliases(self):
        get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        url = f"{self.n8n_prefix}/corporate-card/revenues/"
        body = {
            "date": "2026-03-19T19:00:00.000Z",
            "amount": "15000",
            "note": "alias note",
            "currency": "UZS",
            "operation": "Top-up",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        row = CardRevenue.objects.latest("id")
        self.assertEqual(str(row.total_sum), "15000.00")
        self.assertEqual(row.comment, "alias note")

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
        # Title is derived from tenant name at model-level.
        self.assertEqual(req.title, self.tenant.name)

    def test_request_frontend_create_gateway_allows_requester_role(self):
        url = f"{self.n8n_prefix}/requests/ai-create/"
        body = {
            "title": "AI created request",
            "description": "from assistant",
            "amount": "1200.00",
            "currency": "UZS",
            "payment_type": Request.PAYMENT_TYPE_CASH,
            "urgency": Request.URGENCY_NORMAL,
            "billing_date": "2026-04-01",
            # non-admin requester field should be ignored (same as frontend behavior)
            "requester": self.admin.id,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.other))
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(pk=res.data["id"])
        self.assertEqual(req.tenant_id, self.tenant.id)
        self.assertEqual(req.created_by_id, self.other.id)
        self.assertEqual(req.requester_id, self.other.id)
        self.assertTrue(Approval.objects.filter(request=req).exists())

    def test_request_frontend_create_gateway_requires_requests_module(self):
        TenantModuleConfig.objects.filter(
            tenant=self.tenant,
            module_key="requests",
        ).update(is_enabled=False)
        url = f"{self.n8n_prefix}/requests/ai-create/"
        body = {
            "title": "AI created request",
            "amount": "1200.00",
            "currency": "UZS",
            "payment_type": Request.PAYMENT_TYPE_CASH,
            "urgency": Request.URGENCY_NORMAL,
            "billing_date": "2026-04-01",
        }
        res = self.client.post(url, body, format="json", **self._headers(self.other))
        self.assertEqual(res.status_code, 403)

    def test_requests_amortization_endpoint_works_without_jwt(self):
        url = f"{self.n8n_prefix}/requests/amortization/"
        res = self.client.get(
            url,
            HTTP_HOST="acme.example.com",
            HTTP_X_N8N_INTEGRATION_TOKEN="integ-test-secret",
        )
        self.assertEqual(res.status_code, 200, res.content)

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

    def test_request_upsert_resolves_numeric_cash_expense_id_to_canonical(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        cash_expense = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="1-000000343",
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
            "id": 5013,
            "title": "Imported request canonicalize cash id",
            "description": "from n8n",
            "amount": "1200.00",
            "currency": "UZS",
            "payment_type": "Наличные",
            "urgency": "Обычно",
            "requester": self.requester.id,
            "status": "DRAFT",
            "billing_date": "2026-04-01",
            "expense_id": "343",
            "expense_year": 2026,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(pk=5013)
        self.assertEqual(req.expense_ref_id, cash_expense.id)
        self.assertEqual(req.expense_id, "1-000000343")

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

    def test_request_upsert_does_not_resolve_cash_expense_when_amount_mismatch(self):
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Cash amt mismatch")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        CashExpense.objects.create(
            tenant=self.tenant,
            external_id="CASH-AMT-MIS",
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
            "id": 5014,
            "title": "Amount mismatch",
            "description": "from n8n",
            "amount": "500.00",
            "currency": "UZS",
            "payment_type": "Наличные",
            "urgency": "Обычно",
            "requester": self.requester.id,
            "status": "DRAFT",
            "billing_date": "2026-04-01",
            "expense_id": "CASH-AMT-MIS",
            "expense_year": 2026,
        }
        res = self.client.post(url, body, format="json", **self._headers(self.admin))
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(pk=5014)
        self.assertEqual(req.expense_id, "CASH-AMT-MIS")
        self.assertIsNone(req.expense_ref_id)

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
            "approver_recipient_id": "555001",
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
        self.assertEqual(appr.approver_recipient_id, "555001")

        res2 = self.client.post(
            url,
            {**body, "decision": "approved"},
            format="json",
            **self._headers(self.admin),
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        appr.refresh_from_db()
        self.assertEqual(appr.decision, "approved")


@override_settings(
    BASE_DOMAIN="example.com",
    N8N_INTEGRATION_TOKEN="integ-test-secret",
    ALLOWED_HOSTS=["acme.example.com", "testserver"],
)
class N8nBankStatementDuplicateTests(APITestCase):
    """
    Verify that re-uploading a bank statement skips duplicate transactions
    instead of failing the entire batch import.
    """

    def setUp(self):
        su, _ = User.objects.update_or_create(pk=1, defaults={"username": "n8n_system"})
        if not su.has_usable_password():
            su.set_unusable_password()
            su.save(update_fields=["password"])

        self.tenant = Tenant.objects.create(name="BankCo", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="bank_admin", password="pass12345")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)

        prefix = settings.N8N_INTEGRATION_URL_PREFIX.rstrip("/")
        self.expense_batch_url = f"{prefix}/bank/expenses/batch/"
        self.revenue_batch_url = f"{prefix}/bank/revenues/batch/"

    def _headers(self):
        access = str(RefreshToken.for_user(self.admin).access_token)
        return {
            "HTTP_HOST": "acme.example.com",
            "HTTP_X_N8N_INTEGRATION_TOKEN": "integ-test-secret",
            "HTTP_AUTHORIZATION": f"Bearer {access}",
        }

    def _expense_item(self, doc_no, *, debit_turnover="1000.00", doc_date="2026-04-01"):
        return {
            "row_no": 1,
            "doc_date": doc_date,
            "process_date": doc_date,
            "doc_no": doc_no,
            "account_no": "20208000999999999999",
            "debit_turnover": debit_turnover,
            "payment_purpose": "Тест дублей апрель",
        }

    def _revenue_item(self, doc_no, *, kredit_turnover="1000.00", doc_date="2026-04-01"):
        return {
            "row_no": 1,
            "doc_date": doc_date,
            "process_date": doc_date,
            "doc_no": doc_no,
            "account_no": "20208000999999991",
            "account_name": "ООО Тест",
            "inn": "987654321",
            "mfo": "01001",
            "kredit_turnover": kredit_turnover,
            "payment_purpose": "Тест дублей апрель",
        }

    # ── Bank Expenses ────────────────────────────────────────────────────────

    def test_expense_batch_second_upload_skips_all(self):
        """Re-uploading the same expense statement returns 200 with all records skipped."""
        batch = [self._expense_item("BEXP-DUP-1"), self._expense_item("BEXP-DUP-2")]

        r1 = self.client.post(self.expense_batch_url, batch, format="json", **self._headers())
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(r1.data["count"], 2)
        self.assertEqual(r1.data["skipped"], 0)
        self.assertEqual(BankExpense.objects.filter(tenant=self.tenant).count(), 2)

        r2 = self.client.post(self.expense_batch_url, batch, format="json", **self._headers())
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.data["count"], 0)
        self.assertEqual(r2.data["skipped"], 2)
        # Existing records untouched — still exactly 2.
        self.assertEqual(BankExpense.objects.filter(tenant=self.tenant).count(), 2)

    def test_expense_batch_new_records_inserted_duplicates_skipped(self):
        """Mixed batch: new transactions are imported, duplicate ones are silently skipped."""
        r1 = self.client.post(
            self.expense_batch_url,
            [self._expense_item("BEXP-MIX-1")],
            format="json",
            **self._headers(),
        )
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(BankExpense.objects.filter(tenant=self.tenant).count(), 1)

        batch = [
            self._expense_item("BEXP-MIX-1"),  # duplicate — must be skipped
            self._expense_item("BEXP-MIX-2"),  # new — must be inserted
        ]
        r2 = self.client.post(self.expense_batch_url, batch, format="json", **self._headers())
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.data["count"], 1)
        self.assertEqual(r2.data["skipped"], 1)
        self.assertEqual(BankExpense.objects.filter(tenant=self.tenant).count(), 2)
        self.assertTrue(BankExpense.objects.filter(tenant=self.tenant, doc_no="BEXP-MIX-2").exists())

    def test_expense_batch_validation_error_still_rolls_back(self):
        """A genuine validation error (not a duplicate) must still fail the batch and roll back."""
        batch = [
            self._expense_item("BEXP-VALERR-1"),
            {**self._expense_item("BEXP-VALERR-2"), "debit_turnover": "not-a-number"},
        ]
        res = self.client.post(self.expense_batch_url, batch, format="json", **self._headers())
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.data.get("error_type"), "batch_item_failed")
        self.assertEqual(res.data.get("failed_index"), 1)
        # Rollback: the valid first item must not have been persisted.
        self.assertFalse(BankExpense.objects.filter(tenant=self.tenant, doc_no="BEXP-VALERR-1").exists())

    def test_expense_batch_duplicate_does_not_overwrite_existing_record(self):
        """Skipping a duplicate must leave the original record completely unchanged."""
        r1 = self.client.post(
            self.expense_batch_url,
            [self._expense_item("BEXP-OVERWRITE-1", debit_turnover="500.00")],
            format="json",
            **self._headers(),
        )
        self.assertEqual(r1.status_code, 200, r1.content)
        original = BankExpense.objects.get(tenant=self.tenant, doc_no="BEXP-OVERWRITE-1")
        original_pk = original.pk
        original_created_at = original.created_at

        # Re-upload the same item — should be skipped, not overwritten.
        r2 = self.client.post(
            self.expense_batch_url,
            [self._expense_item("BEXP-OVERWRITE-1", debit_turnover="500.00")],
            format="json",
            **self._headers(),
        )
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.data["skipped"], 1)

        original.refresh_from_db()
        self.assertEqual(original.pk, original_pk)
        self.assertEqual(original.created_at, original_created_at)
        self.assertEqual(str(original.debit_turnover), "500.00")

    # ── Bank Revenues ────────────────────────────────────────────────────────

    def test_revenue_batch_second_upload_skips_all(self):
        """Re-uploading the same revenue statement returns 200 with all records skipped."""
        batch = [self._revenue_item("BREV-DUP-1"), self._revenue_item("BREV-DUP-2")]

        r1 = self.client.post(self.revenue_batch_url, batch, format="json", **self._headers())
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(r1.data["count"], 2)
        self.assertEqual(r1.data["skipped"], 0)
        self.assertEqual(BankRevenue.objects.filter(tenant=self.tenant).count(), 2)

        r2 = self.client.post(self.revenue_batch_url, batch, format="json", **self._headers())
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.data["count"], 0)
        self.assertEqual(r2.data["skipped"], 2)
        self.assertEqual(BankRevenue.objects.filter(tenant=self.tenant).count(), 2)

    def test_revenue_batch_new_records_inserted_duplicates_skipped(self):
        """Mixed revenue batch: new transactions imported, duplicates silently skipped."""
        r1 = self.client.post(
            self.revenue_batch_url,
            [self._revenue_item("BREV-MIX-1")],
            format="json",
            **self._headers(),
        )
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(BankRevenue.objects.filter(tenant=self.tenant).count(), 1)

        batch = [
            self._revenue_item("BREV-MIX-1"),  # duplicate — must be skipped
            self._revenue_item("BREV-MIX-2"),  # new — must be inserted
        ]
        r2 = self.client.post(self.revenue_batch_url, batch, format="json", **self._headers())
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.data["count"], 1)
        self.assertEqual(r2.data["skipped"], 1)
        self.assertEqual(BankRevenue.objects.filter(tenant=self.tenant).count(), 2)
        self.assertTrue(BankRevenue.objects.filter(tenant=self.tenant, doc_no="BREV-MIX-2").exists())


@override_settings(
    BASE_DOMAIN="example.com",
    N8N_INTEGRATION_TOKEN="integ-test-secret",
    ALLOWED_HOSTS=["acme.example.com", "testserver"],
)
class NotifyRequestPayedTests(APITestCase):
    def setUp(self):
        su, _ = User.objects.update_or_create(pk=1, defaults={"username": "n8n_system"})
        if not su.has_usable_password():
            su.set_unusable_password()
            su.save(update_fields=["password"])
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="notify_admin", password="pass12345")

    def _make_payed_request(self):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            billing_date=date(2026, 1, 1),
            amount="500.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            payment_purpose="Test purpose",
            status=Request.STATUS_PAYED,
        )

    @patch("apps.modules.n8n_integration.event_handlers.threading.Thread")
    @patch("apps.modules.n8n_integration.views._n8n_session.post")
    def test_sends_correct_url_and_payload(self, mock_post, mock_thread):
        mock_post.return_value = Mock(status_code=200)
        # Run _send synchronously by calling the target directly
        mock_thread.side_effect = lambda target, daemon: Mock(start=target)

        from apps.modules.n8n_integration.event_handlers import notify_request_payed
        req = self._make_payed_request()
        notify_request_payed(request_obj=req)

        mock_post.assert_called_once()
        call_url = mock_post.call_args.args[0]
        self.assertIn("/n8n/events/new-payed-request", call_url)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["id"], req.id)
        self.assertEqual(payload["status"], "PAYED")
        self.assertEqual(payload["tenant"], "acme")
        self.assertEqual(payload["amount"], "500.00")

    @override_settings(BASE_DOMAIN="")
    @patch("apps.modules.n8n_integration.views._n8n_session.post")
    def test_skips_when_no_base_domain(self, mock_post):
        from apps.modules.n8n_integration.event_handlers import notify_request_payed
        req = self._make_payed_request()
        notify_request_payed(request_obj=req)
        mock_post.assert_not_called()

    # Override is required: class-level sets N8N_INTEGRATION_TOKEN="integ-test-secret",
    # which is the settings fallback in get_n8n_integration_settings(). Without this
    # override the fallback would supply a non-empty token and the guard would not fire.
    @override_settings(N8N_INTEGRATION_TOKEN="")
    @patch("apps.modules.n8n_integration.views._n8n_session.post")
    def test_skips_when_no_token(self, mock_post):
        from apps.modules.n8n_integration.event_handlers import notify_request_payed
        req = self._make_payed_request()
        notify_request_payed(request_obj=req)
        mock_post.assert_not_called()


@override_settings(
    BASE_DOMAIN="example.com",
    N8N_INTEGRATION_TOKEN="integ-test-secret",
    ALLOWED_HOSTS=["acme.example.com", "testserver"],
)
class N8nUnmatchedExpensesTests(APITestCase):
    def setUp(self):
        su, _ = User.objects.update_or_create(pk=1, defaults={"username": "n8n_system"})
        if not su.has_usable_password():
            su.set_unusable_password()
            su.save(update_fields=["password"])

        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="unmatched_admin", password="pass12345")
        self.approver = User.objects.create_user(username="unmatched_approver", password="pass12345")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.approver, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)

        for module_key in ("cash", "bank", "requests", "vendors"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=module_key, is_enabled=True)

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        self.cash_pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg,
            payment_type=Request.PAYMENT_TYPE_CASH,
            is_enabled=True,
        )
        cash_step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.cash_pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=cash_step, approver_user=self.approver)

        self.transfer_pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg,
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            is_enabled=True,
        )
        for step_no in (1, 2):
            step_cfg = RequestApprovalStepConfig.objects.create(
                payment_type_config=self.transfer_pt_cfg,
                step=step_no,
                step_type=Approval.STEP_TYPE_SERIAL,
                is_enabled=True,
            )
            RequestApprovalStepApproverConfig.objects.create(
                step_config=step_cfg,
                approver_user=self.approver,
            )

        self.cash_wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        self.bank_wallet = get_or_create_bank_wallet(tenant=self.tenant)
        self.vendor = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_TRANSFER,
            name="Transfer Vendor",
            inn="123456789",
            account_number="20208000999999999999",
            created_by=self.admin,
        )
        self.n8n_prefix = settings.N8N_INTEGRATION_URL_PREFIX.rstrip("/")
        self.url = f"{self.n8n_prefix}/unmatched-expenses/"

    def _headers(self, *, integration=True):
        h = {"HTTP_HOST": "acme.example.com"}
        if integration:
            h["HTTP_X_N8N_INTEGRATION_TOKEN"] = "integ-test-secret"
        return h

    def test_unmatched_expenses_requires_integration_token(self):
        res = self.client.get(self.url, **self._headers(integration=False))
        self.assertEqual(res.status_code, 401)

    def test_cash_missing_paid_request_respects_optional_rules(self):
        dt = datetime(2026, 5, 20, 12, 0, 0)
        required_missing = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="n8n-cash-req-miss",
            confirmed=True,
            title="Required missing",
            amount="10.00",
            currency="UZS",
            wallet=self.cash_wallet,
            expense_at=dt,
            expense_year=2026,
            expense_month=5,
            expense_day=20,
            payload={},
            created_by=self.admin,
        )
        CashExpense.objects.create(
            tenant=self.tenant,
            external_id="n8n-cash-opt",
            confirmed=True,
            title="Optional by rule",
            amount="30.00",
            currency="UZS",
            wallet=self.cash_wallet,
            expense_at=dt,
            expense_year=2026,
            expense_month=5,
            expense_day=20,
            payload={},
            created_by=self.admin,
        )
        self.cash_pt_cfg.request_not_required_rules = [
            {"field": "title", "operator": "eq", "value": "Optional by rule"},
        ]
        self.cash_pt_cfg.save(update_fields=["request_not_required_rules"])

        res = self.client.get(self.url, **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        missing_ids = {row["id"] for row in data["cash"]["missing_paid_request"]}
        self.assertIn(required_missing.id, missing_ids)
        self.assertEqual(data["cash"]["counts"]["missing_paid_request"], 1)
        self.assertIn("rules", data["cash"])
        self.assertIn("request_not_required_rules", data["cash"]["rules"])

    def test_bank_expense_with_linked_request_in_progress(self):
        d = date(2026, 5, 21)
        bank_expense = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            wallet=self.bank_wallet,
            row_no=1,
            doc_date=d,
            process_date=d,
            expense_year=2026,
            expense_month=5,
            expense_day=21,
            doc_no="N8N-LINKED",
            debit_turnover="100.00",
            payment_purpose="Linked purpose",
            vendor=self.vendor,
        )
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Linked",
            amount="100.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=d,
            status=Request.STATUS_PROGRESS_1,
            expense_ref_id=bank_expense.id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            expense_id=bank_expense.doc_no,
            expense_year=bank_expense.expense_year,
        )
        Approval.objects.create(
            request=req,
            approver_user=self.approver,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        res = self.client.get(self.url, **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        linked_ids = {row["id"] for row in data["bank"]["linked_request_in_progress"]}
        self.assertIn(bank_expense.id, linked_ids)
        row = next(r for r in data["bank"]["linked_request_in_progress"] if r["id"] == bank_expense.id)
        self.assertEqual(row["matched_request_id"], req.id)
        self.assertEqual(row["matched_request_status"], Request.STATUS_PROGRESS_1)
        self.assertEqual(row["pending_approval_step"], 1)

    def test_transfer_request_without_expense_in_pending_approval(self):
        d = date(2026, 5, 22)
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="No expense yet",
            amount="5000.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=d,
            status=Request.STATUS_PROGRESS_2,
            payment_purpose="Аванс",
        )
        Approval.objects.create(
            request=req,
            approver_user=self.approver,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )
        Approval.objects.create(
            request=req,
            approver_user=self.approver,
            step=2,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        res = self.client.get(self.url, **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        pt_block = data["requests_pending_approval"][Request.PAYMENT_TYPE_TRANSFER]
        without = pt_block["without_expense_link"]
        self.assertEqual(len(without), 1)
        self.assertEqual(without[0]["id"], req.id)
        self.assertFalse(without[0]["expense_linked"])
        self.assertIsNone(without[0]["expense_ref_id"])
        self.assertEqual(without[0]["pending_approval_step"], 2)
        self.assertEqual(without[0]["pending_approver_user_ids"], [self.approver.id])
        bank_missing_ids = {row["id"] for row in data["bank"]["missing_paid_request"]}
        bank_linked_ids = {row["id"] for row in data["bank"]["linked_request_in_progress"]}
        self.assertNotIn(req.id, bank_missing_ids)
        self.assertNotIn(req.id, bank_linked_ids)

