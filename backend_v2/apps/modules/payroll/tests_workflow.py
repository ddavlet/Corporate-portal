import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from apps.modules.cashier.models import CashExpense
from apps.modules.n8n_integration.serializers import N8nPayrollLineImportSerializer
from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine, PayrollPayout
from apps.modules.payroll.services import (
    accept_document,
    cancel_draft_document,
    copy_document,
    create_draft_document,
    current_request_for_document,
    maybe_create_linked_request,
    update_draft_document,
)
from apps.modules.requests.approval_workflow import confirm_approval_by_id
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestComment,
)
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


class N8nPayrollEmployeeResolutionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="N8nEmp", subdomain="n8n-emp", is_active=True)
        self.request = APIRequestFactory().post("/")
        self.request.tenant = self.tenant

    def _import(self, **overrides):
        data = {"doc_id": "1-000000009", "line_no": 1, "employee": "  Alice  ", "item": "Оклад", "sum": "100.00"}
        data.update(overrides)
        ser = N8nPayrollLineImportSerializer(data=data, context={"request": self.request})
        ser.is_valid(raise_exception=True)
        return ser.save()

    def test_create_resolves_or_creates_employee(self):
        existing = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        line = self._import()
        self.assertEqual(line.employee_fk_id, existing.id)
        line2 = self._import(line_no=2, employee="Bob")
        self.assertEqual(line2.employee_fk.full_name, "Bob")
        self.assertEqual(line2.document.status, PayrollDocument.STATUS_ACCEPTED)

    def test_update_re_resolves_employee_when_name_changes(self):
        line = self._import()
        ser = N8nPayrollLineImportSerializer(
            instance=line, data={"employee": "Carol"}, partial=True, context={"request": self.request}
        )
        ser.is_valid(raise_exception=True)
        line = ser.save()
        self.assertEqual(line.employee_fk.full_name, "Carol")


def make_payroll_approval_chain(tenant, approver, payer=None):
    cfg = RequestApprovalConfig.objects.create(tenant=tenant)
    pt = RequestApprovalPaymentTypeConfig.objects.create(
        config=cfg, payment_type=Request.PAYMENT_TYPE_PAYROLL, is_enabled=True
    )
    s1 = RequestApprovalStepConfig.objects.create(payment_type_config=pt, step=1, is_enabled=True)
    RequestApprovalStepApproverConfig.objects.create(step_config=s1, approver_user=approver)
    if payer is not None:
        s2 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt, step=2, is_enabled=True, step_type=Approval.STEP_TYPE_PAYMENT
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=s2, approver_user=payer)


@patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None)
class PayrollDraftWorkflowTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Draft", subdomain="draft", is_active=True)
        self.system = User.objects.filter(pk=1).first() or User.objects.create_user(id=1, username="system", password="x")
        self.user = User.objects.create_user(username="draft-user", password="x")
        self.approver = User.objects.create_user(username="draft-approver", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.approver, is_active=True)
        make_payroll_approval_chain(self.tenant, self.approver)
        self.alice = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        self.bob = Employee.objects.create(tenant=self.tenant, full_name="Bob")
        self.period = datetime.date(2026, 9, 1)

    def _draft(self):
        return create_draft_document(
            tenant=self.tenant, user=self.user, period_month=self.period, kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("700")}, {"employee": self.bob, "sum": Decimal("300")}],
        )

    def test_create_draft(self, _tg):
        doc = self._draft()
        self.assertEqual(doc.status, PayrollDocument.STATUS_DRAFT)
        self.assertEqual(doc.source, PayrollDocument.SOURCE_PORTAL)
        lines = list(doc.lines.order_by("line_no"))
        self.assertEqual([l.employee_fk_id for l in lines], [self.alice.id, self.bob.id])
        self.assertEqual(lines[0].item, "Зарплата")
        self.assertEqual(lines[0].period_start, datetime.date(2026, 9, 1))
        self.assertEqual(lines[0].period_end, datetime.date(2026, 9, 30))

    def test_update_draft_replaces_lines(self, _tg):
        doc = self._draft()
        update_draft_document(
            document=doc, period_month=datetime.date(2026, 10, 15), kind="bonus",
            lines_data=[{"employee": self.bob, "sum": Decimal("50")}],
        )
        doc.refresh_from_db()
        self.assertEqual(doc.period_month, datetime.date(2026, 10, 1))
        self.assertEqual(list(doc.lines.values_list("employee_fk_id", "sum")), [(self.bob.id, Decimal("50.00"))])

    def test_update_and_cancel_only_for_draft(self, _tg):
        doc = self._draft()
        accept_document(document=doc, actor=self.user)
        with self.assertRaises(ValidationError):
            update_draft_document(document=doc, period_month=self.period, kind="salary", lines_data=[])
        with self.assertRaises(ValidationError):
            cancel_draft_document(document=doc)

    def test_cancel_draft(self, _tg):
        doc = cancel_draft_document(document=self._draft())
        self.assertEqual(doc.status, PayrollDocument.STATUS_CANCELLED)

    def test_copy_makes_new_draft_for_next_month(self, _tg):
        src = self._draft()
        copy = copy_document(document=src, user=self.user)
        self.assertNotEqual(copy.pk, src.pk)
        self.assertEqual(copy.status, PayrollDocument.STATUS_DRAFT)
        self.assertEqual(copy.period_month, datetime.date(2026, 10, 1))
        self.assertEqual(copy.lines.count(), 2)

    def test_copy_of_n8n_document_sums_lines_per_employee(self, _tg):
        src = PayrollDocument.objects.create(tenant=self.tenant, doc_id="1-000000002")
        for no, (emp, amount) in enumerate([(self.alice, "100"), (self.alice, "50"), (self.bob, "10")], start=1):
            PayrollLine.objects.create(
                document=src, line_no=no, employee=emp.full_name, employee_fk=emp, item="x", sum=amount,
            )
        copy = copy_document(document=src, user=self.user)
        self.assertEqual(
            sorted(copy.lines.values_list("employee_fk_id", "sum")),
            sorted([(self.alice.id, Decimal("150.00")), (self.bob.id, Decimal("10.00"))]),
        )

    def test_accept_creates_request_regardless_of_tenant_flag(self, _tg):
        self.assertFalse(self.tenant.create_payment_request_on_payroll_accrual)
        doc = self._draft()
        req = accept_document(document=doc, actor=self.user)
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertEqual(doc.payout_mode, PayrollDocument.PAYOUT_MODE_LEGACY)
        self.assertEqual(req.amount, Decimal("1000.00"))
        self.assertEqual(current_request_for_document(doc), req)

    def test_accept_takes_payout_mode_from_tenant(self, _tg):
        self.tenant.payroll_payout_mode = Tenant.PAYROLL_PAYOUT_MODE_PORTAL
        self.tenant.save(update_fields=["payroll_payout_mode"])
        doc = self._draft()
        accept_document(document=doc, actor=self.user)
        doc.refresh_from_db()
        self.assertEqual(doc.payout_mode, PayrollDocument.PAYOUT_MODE_PORTAL)

    def test_reject_returns_draft_and_reaccept_creates_new_request(self, _tg):
        doc = self._draft()
        first = accept_document(document=doc, actor=self.user)
        approval = Approval.objects.get(request=first, step=1)
        confirm_approval_by_id(
            tenant=self.tenant, approval_id=approval.id, approver_user_id=self.approver.id,
            decision=Approval.DECISION_REJECTED,
        )
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_DRAFT)
        self.assertTrue(RequestComment.objects.filter(request=first, body__contains="черновик").exists())
        self.assertIsNone(current_request_for_document(doc))
        second = accept_document(document=doc, actor=self.user)
        self.assertNotEqual(first.id, second.id)

    def test_legacy_rejected_request_is_not_recreated(self, _tg):
        self.tenant.create_payment_request_on_payroll_accrual = True
        self.tenant.save(update_fields=["create_payment_request_on_payroll_accrual"])
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id="1-000000003")
        PayrollLine.objects.create(document=doc, line_no=1, employee="Alice", employee_fk=self.alice, item="x", sum="10")
        first = maybe_create_linked_request(doc)
        Request.objects.filter(pk=first.pk).update(status=Request.STATUS_REJECTED)
        again = maybe_create_linked_request(doc)
        self.assertEqual(again.pk, first.pk)
