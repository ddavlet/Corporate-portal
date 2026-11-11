from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfigStep,
    InvestmentProjectApprovalConfigStep,
    InvestmentReturnApproval,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.investments.services import (
    list_invest_return_action_items,
    list_project_investment_action_items,
)
from apps.tenants.models import Tenant

User = get_user_model()


class _Fixtures:
    def make_base(self):
        self.tenant = Tenant.objects.create(name="InvAI", subdomain="invai", is_active=True)
        self.other_tenant = Tenant.objects.create(name="InvAI2", subdomain="invai2", is_active=True)
        self.user = User.objects.create_user(username="invai-user", password="x")
        self.other_user = User.objects.create_user(username="invai-other", password="x")
        self.company = InvestCompany.objects.create(tenant=self.tenant, name="Lemon", created_by=self.user)


class InvestReturnActionItemsTests(_Fixtures, TestCase):
    SERIAL = InvestmentApprovalConfigStep.STEP_TYPE_SERIAL
    NOTIFICATION = InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION

    def setUp(self):
        self.make_base()

    def _return(self, *, tenant=None, company=None):
        return InvestReturn.objects.create(
            tenant=tenant or self.tenant,
            company=company,
            date=date(2026, 11, 1),
            billing_date=date(2026, 11, 1),
            sum=Decimal("1200.00"),
            currency="USD",
            type=InvestReturn.ReturnType.DIVIDEND,
            recipient=InvestReturn.Recipient.INVESTOR,
            created_by=self.user,
        )

    def _approval(self, invest_return, *, step, user=None, step_type=None, decision=None):
        return InvestmentReturnApproval.objects.create(
            tenant=invest_return.tenant,
            invest_return=invest_return,
            step=step,
            step_type=step_type or self.SERIAL,
            approver_user=user or self.user,
            decision=decision or InvestmentReturnApproval.DECISION_PENDING,
        )

    def _items(self, user=None, tenant=None):
        return list_invest_return_action_items(tenant=tenant or self.tenant, user=user or self.user)

    def test_minimal_pending_step_is_listed(self):
        ir = self._return(company=self.company)
        approval = self._approval(ir, step=1)
        self._approval(ir, step=2, user=self.other_user)

        items = self._items()

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["kind"], "invest_return")
        self.assertEqual(item["id"], ir.id)
        self.assertEqual(item["approval_id"], approval.id)
        self.assertEqual(item["step"], 1)
        self.assertEqual(item["step_type"], self.SERIAL)
        self.assertEqual(item["title"], f"Выплата инвестиции #{ir.id} · Lemon")
        self.assertEqual(item["amount"], Decimal("1200.00"))
        self.assertEqual(item["currency"], "USD")
        self.assertEqual(item["type_code"], InvestReturn.ReturnType.DIVIDEND)
        self.assertEqual(item["type_label"], "Дивиденды")
        self.assertEqual(item["created_at"], ir.created_at)
        self.assertEqual(item["link"], f"/investments?tab=returns&open={ir.id}")

    def test_later_step_is_not_listed_while_earlier_is_pending(self):
        ir = self._return()
        self._approval(ir, step=1, user=self.other_user)
        self._approval(ir, step=2)

        self.assertEqual(self._items(), [])

    def test_later_step_is_listed_after_earlier_approved(self):
        ir = self._return()
        self._approval(ir, step=1, user=self.other_user, decision=InvestmentReturnApproval.DECISION_APPROVED)
        approval = self._approval(ir, step=2)

        self.assertEqual([i["approval_id"] for i in self._items()], [approval.id])

    def test_flow_with_rejected_row_is_not_listed(self):
        ir = self._return()
        self._approval(ir, step=1, user=self.other_user, decision=InvestmentReturnApproval.DECISION_REJECTED)
        self._approval(ir, step=1)

        self.assertEqual(self._items(), [])

    def test_notification_step_is_not_listed(self):
        ir = self._return()
        self._approval(ir, step=1, step_type=self.NOTIFICATION)

        self.assertEqual(self._items(), [])

    def test_confirmed_return_is_not_listed(self):
        ir = self._return()
        self._approval(ir, step=1)
        # Bypass confirmation signals: only the flag matters here.
        InvestReturn.objects.filter(pk=ir.pk).update(confirmed=True)

        self.assertEqual(self._items(), [])

    def test_other_tenant_and_other_user_are_not_listed(self):
        foreign = self._return(tenant=self.other_tenant)
        self._approval(foreign, step=1)
        not_mine = self._return()
        self._approval(not_mine, step=1, user=self.other_user)

        self.assertEqual(self._items(), [])
        self.assertEqual([i["id"] for i in self._items(tenant=self.other_tenant)], [foreign.id])

    def test_query_count_does_not_grow_with_returns(self):
        for _ in range(4):
            self._approval(self._return(company=self.company), step=1)

        with CaptureQueriesContext(connection) as ctx:
            items = self._items()

        self.assertEqual(len(items), 4)
        self.assertEqual(len(ctx.captured_queries), 1)


class ProjectInvestmentActionItemsTests(_Fixtures, TestCase):
    SERIAL = InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL
    NOTIFICATION = InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION

    def setUp(self):
        self.make_base()

    def _investment(self, *, tenant=None, company=None):
        return ProjectInvestment.objects.create(
            tenant=tenant or self.tenant,
            company=company,
            date=date(2026, 11, 1),
            amount=Decimal("5000.00"),
            currency="USD",
            funding_method=ProjectInvestment.FundingMethod.CASH,
            created_by=self.user,
        )

    def _approval(self, investment, *, step, user=None, step_type=None, decision=None):
        return ProjectInvestmentApproval.objects.create(
            tenant=investment.tenant,
            project_investment=investment,
            step=step,
            step_type=step_type or self.SERIAL,
            approver_user=user or self.user,
            decision=decision or ProjectInvestmentApproval.DECISION_PENDING,
        )

    def _items(self, user=None, tenant=None):
        return list_project_investment_action_items(tenant=tenant or self.tenant, user=user or self.user)

    def test_minimal_pending_step_is_listed(self):
        investment = self._investment(company=self.company)
        approval = self._approval(investment, step=1)
        self._approval(investment, step=2, user=self.other_user)

        items = self._items()

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["kind"], "project_investment")
        self.assertEqual(item["id"], investment.id)
        self.assertEqual(item["approval_id"], approval.id)
        self.assertEqual(item["title"], f"Вложение в проект #{investment.id} · Lemon")
        self.assertEqual(item["amount"], Decimal("5000.00"))
        self.assertEqual(item["type_code"], ProjectInvestment.FundingMethod.CASH)
        self.assertEqual(item["type_label"], "Наличными")
        self.assertEqual(item["link"], f"/investments?tab=investments&open={investment.id}")

    def test_later_step_is_not_listed_while_earlier_is_pending(self):
        investment = self._investment()
        self._approval(investment, step=1, user=self.other_user)
        self._approval(investment, step=2)

        self.assertEqual(self._items(), [])

    def test_flow_with_rejected_row_is_not_listed(self):
        investment = self._investment()
        self._approval(
            investment, step=1, user=self.other_user, decision=ProjectInvestmentApproval.DECISION_REJECTED
        )
        self._approval(investment, step=1)

        self.assertEqual(self._items(), [])

    def test_notification_step_is_not_listed(self):
        investment = self._investment()
        self._approval(investment, step=1, step_type=self.NOTIFICATION)

        self.assertEqual(self._items(), [])

    def test_confirmed_investment_is_not_listed(self):
        investment = self._investment()
        self._approval(investment, step=1)
        # Bypass confirmation signals (cash revenue creation): only the flag matters here.
        ProjectInvestment.objects.filter(pk=investment.pk).update(confirmed=True)

        self.assertEqual(self._items(), [])

    def test_other_tenant_and_other_user_are_not_listed(self):
        foreign = self._investment(tenant=self.other_tenant)
        self._approval(foreign, step=1)
        not_mine = self._investment()
        self._approval(not_mine, step=1, user=self.other_user)

        self.assertEqual(self._items(), [])
        self.assertEqual([i["id"] for i in self._items(tenant=self.other_tenant)], [foreign.id])
