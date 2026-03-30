from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.modules.payroll.models import PayrollDocument, PayrollLine


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

