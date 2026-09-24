import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.payroll.models import Employee, PayrollDocument
from apps.modules.payroll.payouts import create_payout_expense
from apps.modules.payroll.services import accept_document, create_draft_document
from apps.modules.payroll.tests_workflow import make_payroll_approval_chain
from apps.modules.requests.approval_workflow import confirm_approval_by_id
from apps.modules.requests.models import Approval
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
@patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None)
class PayrollWorkflowApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Api", subdomain="payapi", is_active=True, payroll_payout_mode=Tenant.PAYROLL_PAYOUT_MODE_PORTAL
        )
        self.host = "payapi.example.com"
        for key in ("payroll", "cash", "wallets"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)
        self.system = User.objects.filter(pk=1).first() or User.objects.create_user(id=1, username="system", password="x")
        self.director = self._user("api-director", TenantUserRole.ROLE_DIRECTOR)
        self.cashier = self._user("api-cashier", TenantUserRole.ROLE_CASHIER)
        self.accountant = self._user("api-accountant", TenantUserRole.ROLE_ACCOUNTANT)
        self.approver = self._user("api-approver", TenantUserRole.ROLE_APPROVER)
        make_payroll_approval_chain(self.tenant, self.approver)
        self.alice = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")

    def _user(self, username, role):
        user = User.objects.create_user(username=username, password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def _approved_doc(self):
        doc = create_draft_document(
            tenant=self.tenant, user=self.director, period_month=datetime.date(2026, 9, 1), kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("100")}],
        )
        req = accept_document(document=doc, actor=self.director)
        a1 = Approval.objects.get(request=req, step=1)
        confirm_approval_by_id(tenant=self.tenant, approval_id=a1.id, approver_user_id=self.approver.id)
        return doc

    def test_draft_create_edit_accept_flow(self, _tg):
        self.client.force_authenticate(self.director)
        body = {"period_month": "2026-09-01", "kind": "salary", "lines": [{"employee_id": self.alice.id, "sum": "100.00"}]}
        res = self.client.post("/api/payroll/documents/create/", body, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.content)
        doc_id = res.data["id"]
        self.assertEqual(res.data["status"], "draft")
        body["lines"][0]["sum"] = "150.00"
        res = self.client.patch(f"/api/payroll/documents/{doc_id}/", body, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Decimal(res.data["total_sum"]), Decimal("150.00"))
        res = self.client.post(f"/api/payroll/documents/{doc_id}/accept/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["status"], "accepted")
        self.assertIsNotNone(res.data["current_request"])

    def test_draft_validation(self, _tg):
        self.client.force_authenticate(self.director)
        other_tenant = Tenant.objects.create(name="Other", subdomain="other-pay", is_active=True)
        stranger = Employee.objects.create(tenant=other_tenant, full_name="Stranger")
        for lines in (
            [],
            [{"employee_id": self.alice.id, "sum": "1"}, {"employee_id": self.alice.id, "sum": "2"}],
            [{"employee_id": self.alice.id, "sum": "0"}],
            [{"employee_id": stranger.id, "sum": "1"}],
        ):
            res = self.client.post(
                "/api/payroll/documents/create/",
                {"period_month": "2026-09-01", "kind": "salary", "lines": lines},
                format="json", HTTP_HOST=self.host,
            )
            self.assertEqual(res.status_code, 400, lines)

    def test_cancelled_hidden_by_default(self, _tg):
        self.client.force_authenticate(self.director)
        doc = create_draft_document(
            tenant=self.tenant, user=self.director, period_month=datetime.date(2026, 9, 1), kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("1")}],
        )
        self.client.post(f"/api/payroll/documents/{doc.pk}/cancel/", HTTP_HOST=self.host)
        res = self.client.get("/api/payroll/documents/", HTTP_HOST=self.host)
        ids = [r["id"] for r in res.data["results"]]
        self.assertNotIn(doc.pk, ids)
        res = self.client.get("/api/payroll/documents/?status=cancelled", HTTP_HOST=self.host)
        self.assertIn(doc.pk, [r["id"] for r in res.data["results"]])

    def test_cashier_can_pay_but_not_list_documents(self, _tg):
        doc = self._approved_doc()
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.get("/api/payroll/documents/", HTTP_HOST=self.host).status_code, 403)
        res = self.client.get("/api/payroll/payable-documents/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual([d["id"] for d in res.data], [doc.pk])
        res = self.client.get(f"/api/payroll/documents/{doc.pk}/payout-state/", HTTP_HOST=self.host)
        self.assertTrue(res.data["can_pay"])
        res = self.client.post(
            f"/api/payroll/documents/{doc.pk}/payouts/",
            {"wallet_id": self.wallet.id, "date": "2026-09-30", "items": [{"employee_id": self.alice.id, "amount": "40.00"}]},
            format="json", HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        exp_id = res.data["cash_expense_id"]
        res = self.client.get(f"/api/payroll/cash-expenses/{exp_id}/payouts/", HTTP_HOST=self.host)
        self.assertEqual(res.data[0]["full_name"], "Alice")
        self.assertEqual(Decimal(res.data[0]["amount"]), Decimal("40.00"))

    def test_payout_over_limit_is_400(self, _tg):
        doc = self._approved_doc()
        self.client.force_authenticate(self.director)
        res = self.client.post(
            f"/api/payroll/documents/{doc.pk}/payouts/",
            {"wallet_id": self.wallet.id, "date": "2026-09-30", "items": [{"employee_id": self.alice.id, "amount": "100.01"}]},
            format="json", HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Alice", str(res.data))

    def test_accountant_forbidden(self, _tg):
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get("/api/payroll/documents/", HTTP_HOST=self.host).status_code, 403)
        self.assertEqual(self.client.get("/api/payroll/payable-documents/", HTTP_HOST=self.host).status_code, 403)

    def test_close_underpaid_endpoint(self, _tg):
        doc = self._approved_doc()
        self.client.force_authenticate(self.director)
        res = self.client.post(f"/api/payroll/documents/{doc.pk}/close-underpaid/", {"comment": ""}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        res = self.client.post(f"/api/payroll/documents/{doc.pk}/close-underpaid/", {"comment": "ok"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["status"], "closed")

    def test_employees_list_and_create(self, _tg):
        self.client.force_authenticate(self.director)
        res = self.client.post("/api/payroll/employees/create/", {"full_name": "  Bob "}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["full_name"], "Bob")
        res = self.client.post("/api/payroll/employees/create/", {"full_name": "Bob"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        res = self.client.get("/api/payroll/employees/?search=bo", HTTP_HOST=self.host)
        self.assertEqual([e["full_name"] for e in res.data], ["Bob"])

    def test_cash_expense_with_payouts_delete_is_400(self, _tg):
        doc = self._approved_doc()
        exp = create_payout_expense(
            document=doc, wallet_id=self.wallet.id, date=datetime.date(2026, 9, 30),
            items=[{"employee_id": self.alice.id, "amount": Decimal("1")}], actor=self.director,
        )
        admin = self._user("api-admin", TenantUserRole.ROLE_ADMIN)
        self.client.force_authenticate(admin)
        res = self.client.delete(f"/api/cash/expenses/{exp.pk}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400, res.content)

    def test_missing_request_filter_excludes_draft_and_cancelled(self, _tg):
        self.client.force_authenticate(self.director)
        draft = create_draft_document(
            tenant=self.tenant, user=self.director, period_month=datetime.date(2026, 9, 1), kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("1")}],
        )
        res = self.client.get("/api/payroll/documents/?missing_request=true", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn(draft.pk, [r["id"] for r in res.data["results"]])

        # Bypass the action=='list' auto-exclude-cancelled fallback (which would mask
        # the bug on its own) by filtering status=cancelled explicitly alongside
        # missing_request=true: without the fix in views.py the missing_request branch
        # wouldn't exclude cancelled docs, and this combination would still return it.
        cancel_res = self.client.post(f"/api/payroll/documents/{draft.pk}/cancel/", HTTP_HOST=self.host)
        self.assertEqual(cancel_res.status_code, 200, cancel_res.content)
        res = self.client.get(
            "/api/payroll/documents/?missing_request=true&status=cancelled", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn(draft.pk, [r["id"] for r in res.data["results"]])

    def test_tenant_payout_mode_setting(self, _tg):
        self.client.force_authenticate(self.director)
        res = self.client.put(
            "/api/tenant/payroll-settings/",
            {"create_payment_request_on_payroll_accrual": False, "payroll_payout_mode": "legacy"},
            format="json", HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["payroll_payout_mode"], "legacy")
