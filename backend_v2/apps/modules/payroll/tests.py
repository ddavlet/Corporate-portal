from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.common.test_utils import list_results
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.payroll.models import PayrollDocument, PayrollLine

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

