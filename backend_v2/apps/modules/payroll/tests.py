from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.common.test_utils import list_results
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine
from apps.modules.payroll.services import create_payroll_document, maybe_create_linked_request
from apps.modules.requests.models import (
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
)

User = get_user_model()


class PayrollSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

    def test_can_create_document_and_line(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id="DOC-1")
        line = PayrollLine.objects.create(
            document=doc,
            line_no=1,
            employee="John",
            item="Salary",
            description="",
            sum="100.00",
            days_plan=20,
            days_fact=20,
            period_start=timezone.now().date(),
            period_end=timezone.now().date(),
            approval=False,
        )
        self.assertIsNotNone(doc.id)
        self.assertIsNotNone(line.id)
        self.assertEqual(PayrollDocument.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(doc.lines.count(), 1)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class PayrollApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="accountant", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)

        self.host = "acme.example.com"

        today = timezone.now().date()

        self.doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id="PAY-2024-01")
        PayrollLine.objects.create(
            document=self.doc,
            line_no=1,
            employee="Alice Smith",
            item="Salary",
            description="",
            sum="1500.00",
            days_plan=22,
            days_fact=22,
            period_start=today,
            period_end=today,
            approval=False,
        )
        PayrollLine.objects.create(
            document=self.doc,
            line_no=2,
            employee="Bob Jones",
            item="Bonus",
            description="",
            sum="500.00",
            days_plan=22,
            days_fact=20,
            period_start=today,
            period_end=today,
            approval=True,
        )

    def test_list_returns_documents_for_tenant(self):
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/payroll/documents/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        results = list_results(res)
        doc_ids = [r["doc_id"] for r in results]
        self.assertIn("PAY-2024-01", doc_ids)

    def test_list_filtered_by_doc_id(self):
        PayrollDocument.objects.create(tenant=self.tenant, doc_id="PAY-2024-02")

        self.client.force_authenticate(self.user)
        res = self.client.get("/api/payroll/documents/?doc_id=PAY-2024-01", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        results = list_results(res)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["doc_id"], "PAY-2024-01")

    def test_list_filtered_by_employee_search(self):
        other_doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id="PAY-2024-03")
        today = timezone.now().date()
        PayrollLine.objects.create(
            document=other_doc,
            line_no=1,
            employee="Charlie Brown",
            item="Salary",
            description="",
            sum="1200.00",
            days_plan=20,
            days_fact=20,
            period_start=today,
            period_end=today,
            approval=False,
        )

        self.client.force_authenticate(self.user)
        res = self.client.get("/api/payroll/documents/?employee_search=Alice", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        results = list_results(res)
        doc_ids = [r["doc_id"] for r in results]
        self.assertIn("PAY-2024-01", doc_ids)
        self.assertNotIn("PAY-2024-03", doc_ids)

    def test_detail_returns_document_with_lines(self):
        self.client.force_authenticate(self.user)
        res = self.client.get(f"/api/payroll/documents/{self.doc.pk}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["doc_id"], "PAY-2024-01")
        self.assertIn("lines", res.data)
        self.assertEqual(len(res.data["lines"]), 2)
        employees = {line["employee"] for line in res.data["lines"]}
        self.assertIn("Alice Smith", employees)
        self.assertIn("Bob Jones", employees)

    def test_unauthenticated_request_returns_401(self):
        res = self.client.get("/api/payroll/documents/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 401)

    def test_other_tenant_documents_not_visible(self):
        other_tenant = Tenant.objects.create(name="OtherCo", subdomain="otherco", is_active=True)
        other_user = User.objects.create_user(username="other_accountant", password="x")
        TenantMembership.objects.create(tenant=other_tenant, user=other_user, is_active=True)
        TenantUserRole.objects.create(tenant=other_tenant, user=other_user, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantModuleConfig.objects.create(tenant=other_tenant, module_key="payroll", is_enabled=True)

        PayrollDocument.objects.create(tenant=other_tenant, doc_id="OTHER-PAY-001")

        self.client.force_authenticate(self.user)
        res = self.client.get("/api/payroll/documents/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        results = list_results(res)
        doc_ids = [r["doc_id"] for r in results]
        self.assertNotIn("OTHER-PAY-001", doc_ids)
        self.assertIn("PAY-2024-01", doc_ids)


class PayrollNativeDocumentModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NativeAcme", subdomain="native-acme", is_active=True)
        self.user = User.objects.create_user(username="hr_manager", password="x")

    def test_can_create_document_with_null_doc_id_and_created_by(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None, created_by=self.user)
        self.assertIsNone(doc.doc_id)
        self.assertEqual(doc.created_by_id, self.user.id)

    def test_multiple_null_doc_id_documents_allowed_for_same_tenant(self):
        PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        self.assertEqual(PayrollDocument.objects.filter(tenant=self.tenant, doc_id=None).count(), 2)

    def test_line_optional_fields_can_be_null(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        line = PayrollLine.objects.create(
            document=doc,
            line_no=1,
            employee="Jane",
            item="Salary",
            description="",
            sum="100.00",
            days_plan=None,
            days_fact=None,
            period_start=None,
            period_end=None,
            approval=True,
        )
        self.assertIsNone(line.days_plan)
        self.assertIsNone(line.period_start)


class MaybeCreateLinkedRequestTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="LinkReq", subdomain="link-req", is_active=True)
        self.user = User.objects.create_user(username="link-req-user", password="x")
        self.approver = User.objects.create_user(username="link-req-approver", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.approver, is_active=True)

        approval_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=approval_cfg, payment_type=Request.PAYMENT_TYPE_PAYROLL, is_enabled=True,
        )
        step_cfg = RequestApprovalStepConfig.objects.create(payment_type_config=pt_cfg, step=1, is_enabled=True)
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)

        self.doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None, created_by=self.user)
        PayrollLine.objects.create(
            document=self.doc, line_no=1, employee="Alice", item="Salary", description="",
            sum="700.00", days_plan=None, days_fact=None, period_start=None, period_end=None, approval=True,
        )
        PayrollLine.objects.create(
            document=self.doc, line_no=2, employee="Bob", item="Bonus", description="",
            sum="300.00", days_plan=None, days_fact=None, period_start=None, period_end=None, approval=True,
        )

    def test_noop_when_flag_disabled(self):
        self.assertFalse(self.tenant.create_payment_request_on_payroll_accrual)
        result = maybe_create_linked_request(self.doc, actor_user=self.user)
        self.assertIsNone(result)
        self.assertEqual(Request.objects.filter(tenant=self.tenant).count(), 0)

    @patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
    def test_creates_single_request_for_whole_document_when_enabled(self, tg_mock):
        tg_mock.return_value = None
        self.tenant.create_payment_request_on_payroll_accrual = True
        self.tenant.save(update_fields=["create_payment_request_on_payroll_accrual"])

        result = maybe_create_linked_request(self.doc, actor_user=self.user)

        self.assertIsNotNone(result)
        self.assertEqual(Request.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(result.amount, Decimal("1000.00"))
        self.assertEqual(result.payment_type, Request.PAYMENT_TYPE_PAYROLL)
        self.assertEqual(result.expense_ref_id, self.doc.pk)
        self.assertEqual(result.expense_ref_target, Request.EXPENSE_REF_TARGET_PAYROLL)
        self.assertEqual(result.approvals.count(), 1)

    @patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
    def test_idempotent_does_not_duplicate_request(self, tg_mock):
        tg_mock.return_value = None
        self.tenant.create_payment_request_on_payroll_accrual = True
        self.tenant.save(update_fields=["create_payment_request_on_payroll_accrual"])

        first = maybe_create_linked_request(self.doc, actor_user=self.user)
        second = maybe_create_linked_request(self.doc, actor_user=self.user)

        self.assertEqual(first.id, second.id)
        self.assertEqual(Request.objects.filter(tenant=self.tenant).count(), 1)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class PayrollDocumentCreateApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="CreateAcme", subdomain="create-acme", is_active=True)
        self.user = User.objects.create_user(username="create-accountant", password="x")
        self.outsider = User.objects.create_user(username="no-access-user", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
        self.host = "create-acme.example.com"
        self.url = "/api/payroll/documents/create/"

    def test_creates_document_with_lines_and_no_doc_id(self):
        self.client.force_authenticate(self.user)
        payload = {
            "lines": [
                {"employee": "Alice Smith", "item": "Salary", "sum": "1500.00"},
                {"employee": "Bob Jones", "item": "Bonus", "sum": "500.00", "days_plan": 22, "days_fact": 20},
            ]
        }
        res = self.client.post(self.url, payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIsNone(res.data["doc_id"])
        self.assertEqual(len(res.data["lines"]), 2)
        doc = PayrollDocument.objects.get(pk=res.data["id"])
        self.assertEqual(doc.tenant_id, self.tenant.id)
        self.assertEqual(doc.created_by_id, self.user.id)
        self.assertEqual(list(doc.lines.order_by("line_no").values_list("line_no", flat=True)), [1, 2])

    def test_requires_at_least_one_line(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(self.url, {"lines": []}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)

    def test_unauthenticated_returns_401(self):
        res = self.client.post(self.url, {"lines": []}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 401)

    def test_user_without_payroll_module_access_forbidden(self):
        TenantMembership.objects.create(tenant=self.tenant, user=self.outsider, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.outsider, role=TenantUserRole.ROLE_REQUESTER)
        self.client.force_authenticate(self.outsider)
        payload = {"lines": [{"employee": "Alice", "item": "Salary", "sum": "100.00"}]}
        res = self.client.post(self.url, payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 403)

    def test_existing_readonly_list_endpoint_unaffected(self):
        self.client.force_authenticate(self.user)
        payload = {"lines": [{"employee": "Alice", "item": "Salary", "sum": "100.00"}]}
        self.client.post(self.url, payload, format="json", HTTP_HOST=self.host)
        res = self.client.get("/api/payroll/documents/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)


class EmployeeModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="EmpAcme", subdomain="emp-acme", is_active=True)

    def test_can_create_employee(self):
        emp = Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        self.assertIsNotNone(emp.id)
        self.assertEqual(str(emp), "Alice Smith")

    def test_unique_full_name_per_tenant(self):
        Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")

    def test_same_full_name_allowed_in_different_tenant(self):
        other_tenant = Tenant.objects.create(name="EmpOther", subdomain="emp-other", is_active=True)
        Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        emp2 = Employee.objects.create(tenant=other_tenant, full_name="Alice Smith")
        self.assertIsNotNone(emp2.id)

    def test_payroll_line_employee_fk_is_optional_and_links_to_employee(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        emp = Employee.objects.create(tenant=self.tenant, full_name="Bob Jones")
        line_without_fk = PayrollLine.objects.create(
            document=doc, line_no=1, employee="Free text still works", item="Salary",
            description="", sum="100.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=False,
        )
        line_with_fk = PayrollLine.objects.create(
            document=doc, line_no=2, employee="Bob Jones", employee_fk=emp, item="Salary",
            description="", sum="200.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=False,
        )
        self.assertIsNone(line_without_fk.employee_fk)
        self.assertEqual(line_with_fk.employee_fk_id, emp.id)
        self.assertEqual(emp.payroll_lines.count(), 1)
