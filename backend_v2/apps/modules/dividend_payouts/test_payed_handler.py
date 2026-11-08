from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.modules.dividend_payouts.fixtures import FOUNDER_PURPOSE, PARTNER_PURPOSE, DividendPayoutFixtures
from apps.modules.dividend_payouts.models import DividendPayoutLink
from apps.modules.dividend_payouts.services import find_rule, on_request_payed
from apps.modules.investments.models import (
    CbuExchangeRate,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentFormConfig,
    InvestmentReturnApproval,
    InvestReturn,
)
from apps.modules.requests.models import Request
from apps.modules.requests.status_events import dispatch_request_payed_event_handlers
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()

SERVICES = "apps.modules.dividend_payouts.services"


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="")  # n8n PAYED handler must not hit network
class DividendPayedHandlerTests(DividendPayoutFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def _pay(self, req):
        with self.captureOnCommitCallbacks(execute=True):
            on_request_payed(request_obj=req)

    @patch(f"{SERVICES}.route_invest_return_approvals")
    @patch(f"{SERVICES}.create_approvals_for_invest_return")
    def test_creates_invest_return_from_rule(self, create_approvals, route_approvals):
        rule = self.make_rule(recipient=InvestReturn.Recipient.PARTNER, purpose=PARTNER_PURPOSE)
        req = self.make_request(payment_purpose=PARTNER_PURPOSE)

        with self.captureOnCommitCallbacks(execute=True):
            dispatch_request_payed_event_handlers(request_obj=req)  # proves ready() registration

        link = DividendPayoutLink.objects.get(request=req)
        self.assertEqual(link.status, DividendPayoutLink.Status.CREATED)
        self.assertEqual(link.rule_id, rule.id)
        self.assertEqual(link.error, "")
        ir = link.invest_return
        self.assertEqual(ir.tenant_id, self.tenant.id)
        self.assertEqual(ir.type, InvestReturn.ReturnType.PRINCIPAL)
        self.assertEqual(ir.recipient, InvestReturn.Recipient.PARTNER)
        self.assertEqual(ir.sum, Decimal("2500.00"))
        self.assertEqual(ir.currency, "USD")
        self.assertEqual(ir.date, date(2026, 11, 6))
        self.assertEqual(ir.billing_date, date(2026, 10, 1))
        self.assertEqual(ir.comment, f"Получатель: Иванов Иван (заявка #{req.id})")
        self.assertEqual(ir.created_by_id, self.system_user.id)
        self.assertFalse(ir.confirmed)
        create_approvals.assert_called_once_with(invest_return=ir)
        route_approvals.assert_called_once()
        self.assertEqual(route_approvals.call_args.kwargs["invest_return"].pk, ir.pk)

    @patch(f"{SERVICES}.route_invest_return_approvals")
    def test_routing_runs_only_after_commit(self, route_approvals):
        self.make_rule()
        req = self.make_request()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            on_request_payed(request_obj=req)
        route_approvals.assert_not_called()
        self.assertEqual(len(callbacks), 1)

    @patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
    def test_launches_configured_approval_chain(self, tg_send):
        tg_send.return_value = None
        approver = User.objects.create_user(
            username="dp-approver", password="x", telegram_chat_id=93001, telegram_from_id=93002
        )
        TenantMembership.objects.create(tenant=self.tenant, user=approver, is_active=True)
        config = InvestmentApprovalConfig.objects.create(tenant=self.tenant, is_enabled=True)
        step = InvestmentApprovalConfigStep.objects.create(
            config=config, step=1, step_type=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL, is_enabled=True
        )
        InvestmentApprovalConfigStepApprover.objects.create(step=step, approver_user=approver)
        self.make_rule()
        req = self.make_request()

        self._pay(req)

        ir = DividendPayoutLink.objects.get(request=req).invest_return
        approvals = InvestmentReturnApproval.objects.filter(invest_return=ir)
        self.assertEqual(approvals.count(), 1)
        self.assertEqual(approvals.first().decision, InvestmentReturnApproval.DECISION_PENDING)

    @patch(f"{SERVICES}.route_invest_return_approvals")
    def test_uzs_and_case_insensitive_purpose(self, _route):
        self.make_rule(return_type=InvestReturn.ReturnType.DIVIDEND)
        req = self.make_request(payment_purpose="  дивиденды УЧРЕДИТЕЛЮ ", currency="UZS", amount=Decimal("1500000"))

        self._pay(req)

        ir = DividendPayoutLink.objects.get(request=req).invest_return
        self.assertEqual(ir.type, InvestReturn.ReturnType.DIVIDEND)
        self.assertEqual(ir.currency, "UZS")
        self.assertEqual(ir.sum, Decimal("1500000.00"))

    @patch(f"{SERVICES}.tashkent_today", return_value=date(2026, 11, 7))
    @patch(f"{SERVICES}.route_invest_return_approvals")
    def test_empty_payed_at_uses_tashkent_today(self, _route, _today):
        self.make_rule()
        req = self.make_request(payed_at=None)
        self._pay(req)
        self.assertEqual(DividendPayoutLink.objects.get(request=req).invest_return.date, date(2026, 11, 7))

    def test_no_rule_creates_nothing(self):
        self.make_rule()
        req = self.make_request(payment_purpose="Аренда")
        self._pay(req)
        self.assertFalse(DividendPayoutLink.objects.exists())
        self.assertFalse(InvestReturn.objects.exists())

    def test_inactive_rule_creates_nothing(self):
        self.make_rule(is_active=False)
        req = self.make_request()
        self._pay(req)
        self.assertFalse(DividendPayoutLink.objects.exists())
        self.assertFalse(InvestReturn.objects.exists())

    def test_rule_of_other_tenant_is_ignored(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        self.make_rule(tenant=other)
        req = self.make_request()
        self._pay(req)
        self.assertFalse(InvestReturn.objects.exists())

    @patch(f"{SERVICES}.route_invest_return_approvals")
    def test_repeated_payed_does_not_duplicate(self, _route):
        self.make_rule()
        req = self.make_request()
        self._pay(req)
        self._pay(req)
        self.assertEqual(InvestReturn.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(DividendPayoutLink.objects.filter(request=req).count(), 1)

    @patch(f"{SERVICES}.route_invest_return_approvals")
    def test_failed_link_is_retried(self, _route):
        from apps.modules.dividend_payouts.services import retry_failed_link

        self.make_rule()
        req = self.make_request(currency="EUR")
        with self.assertLogs(SERVICES, level="ERROR"):
            self._pay(req)
        link = DividendPayoutLink.objects.get(request=req)
        self.assertEqual(link.status, DividendPayoutLink.Status.FAILED)

        Request.objects.filter(pk=req.pk).update(currency="USD")
        link = retry_failed_link(link)
        self.assertEqual(link.status, DividendPayoutLink.Status.CREATED)
        self.assertEqual(link.error, "")
        self.assertIsNotNone(link.invest_return_id)
        self.assertEqual(DividendPayoutLink.objects.filter(request=req).count(), 1)
        self.assertEqual(InvestReturn.objects.filter(tenant=self.tenant).count(), 1)

    def test_unsupported_currency_stores_failed_link(self):
        self.make_rule()
        req = self.make_request(currency="EUR")
        with self.assertLogs(SERVICES, level="ERROR"):
            self._pay(req)  # must not raise
        link = DividendPayoutLink.objects.get(request=req)
        self.assertEqual(link.status, DividendPayoutLink.Status.FAILED)
        self.assertIsNone(link.invest_return_id)
        self.assertIn("EUR", link.error)
        self.assertFalse(InvestReturn.objects.exists())

    def test_disallowed_return_type_stores_failed_link(self):
        InvestmentFormConfig.objects.create(tenant=self.tenant, allowed_return_types=[InvestReturn.ReturnType.DIVIDEND])
        self.make_rule(return_type=InvestReturn.ReturnType.PRINCIPAL)
        req = self.make_request()
        with self.assertLogs(SERVICES, level="ERROR"):
            self._pay(req)
        link = DividendPayoutLink.objects.get(request=req)
        self.assertEqual(link.status, DividendPayoutLink.Status.FAILED)
        self.assertIn("отключён", link.error)
        self.assertFalse(InvestReturn.objects.exists())

    def test_missing_cbu_rate_stores_failed_link(self):
        CbuExchangeRate.objects.all().delete()
        self.make_rule()
        req = self.make_request()
        with self.assertLogs(SERVICES, level="ERROR"):
            self._pay(req)
        link = DividendPayoutLink.objects.get(request=req)
        self.assertEqual(link.status, DividendPayoutLink.Status.FAILED)
        self.assertNotEqual(link.error, "")
        self.assertFalse(InvestReturn.objects.exists())

    @patch(f"{SERVICES}.create_invest_return_for_request", side_effect=RuntimeError("boom"))
    def test_unexpected_error_does_not_raise(self, _create):
        self.make_rule()
        req = self.make_request()
        with self.assertLogs(SERVICES, level="ERROR"):
            self._pay(req)
        link = DividendPayoutLink.objects.get(request=req)
        self.assertEqual(link.status, DividendPayoutLink.Status.FAILED)
        self.assertEqual(link.error, "boom")

    def test_find_rule_matching(self):
        rule = self.make_rule()
        self.assertEqual(find_rule(self.tenant, FOUNDER_PURPOSE), rule)
        self.assertEqual(find_rule(self.tenant, "  ДИВИДЕНДЫ учредителю  "), rule)
        self.assertIsNone(find_rule(self.tenant, ""))
        self.assertIsNone(find_rule(self.tenant, None))
        self.assertIsNone(find_rule(self.tenant, "Дивиденды"))
