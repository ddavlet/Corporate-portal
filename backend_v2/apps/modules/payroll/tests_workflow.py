from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.modules.cashier.models import CashExpense
from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine, PayrollPayout
from apps.modules.wallets.resolution import get_or_create_cash_wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.tenants.permissions import role_allows_module

User = get_user_model()


class PayrollWorkflowModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Wf", subdomain="wf", is_active=True)
        self.user = User.objects.create_user(username="wf-user", password="x")

    def test_defaults_keep_legacy_behaviour(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id="1-000000001")
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertEqual(doc.source, PayrollDocument.SOURCE_N8N)
        self.assertEqual(doc.payout_mode, PayrollDocument.PAYOUT_MODE_LEGACY)
        self.assertIsNone(doc.period_month)
        self.assertEqual(self.tenant.payroll_payout_mode, Tenant.PAYROLL_PAYOUT_MODE_LEGACY)

    def test_payout_amount_must_be_positive_and_unique_per_expense_employee(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant)
        emp = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        now = timezone.now()
        expense = CashExpense.objects.create(
            tenant=self.tenant, external_id="zp-1-1", amount=Decimal("10"), expense_at=now,
            expense_year=now.year, expense_month=now.month, expense_day=now.day,
            created_by=self.user, wallet=wallet,
        )
        PayrollPayout.objects.create(
            tenant=self.tenant, document=doc, employee=emp, cash_expense=expense, amount=Decimal("10"),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayrollPayout.objects.create(
                tenant=self.tenant, document=doc, employee=emp, cash_expense=expense, amount=Decimal("1"),
            )
        emp2 = Employee.objects.create(tenant=self.tenant, full_name="Bob")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayrollPayout.objects.create(
                tenant=self.tenant, document=doc, employee=emp2, cash_expense=expense, amount=Decimal("0"),
            )


class PayrollRoleAccessTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Roles", subdomain="roles", is_active=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)

    def _user(self, role):
        user = User.objects.create_user(username=f"roles-{role}", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def test_accountant_has_no_payroll_access(self):
        user = self._user(TenantUserRole.ROLE_ACCOUNTANT)
        self.assertFalse(role_allows_module(user=user, tenant=self.tenant, module_key="payroll"))

    def test_director_has_payroll_access(self):
        user = self._user(TenantUserRole.ROLE_DIRECTOR)
        self.assertTrue(role_allows_module(user=user, tenant=self.tenant, module_key="payroll"))
