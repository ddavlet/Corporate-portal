"""Событие «выплата подтверждена»: срабатывает один раз на переходе confirmed False→True после коммита."""
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.modules.investments import events
from apps.modules.investments.approval_services import route_invest_return_approvals
from apps.modules.investments.models import (
    InvestmentApprovalConfigStep,
    InvestmentReturnApproval,
    InvestReturn,
)
from apps.tenants.models import Tenant

User = get_user_model()


class InvestReturnConfirmedEventTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Neuron", subdomain="neuronevt", is_active=True)
        self.admin = User.objects.create_user(username="invret_evt_admin", password="pass12345")
        self.handler = Mock(__name__="test_handler")
        self._saved_handlers = events.INVEST_RETURN_CONFIRMED_HANDLERS
        # Только тестовый обработчик: реальный n8n-обработчик здесь не нужен.
        events.INVEST_RETURN_CONFIRMED_HANDLERS = ()
        events.register_invest_return_confirmed_handler(self.handler)

    def tearDown(self):
        events.INVEST_RETURN_CONFIRMED_HANDLERS = self._saved_handlers

    def _make_return(self, *, confirmed=False):
        return InvestReturn.objects.create(
            tenant=self.tenant,
            date=date(2026, 11, 10),
            billing_date=date(2026, 11, 1),
            sum=Decimal("600000000.00"),
            currency="UZS",
            type=InvestReturn.ReturnType.DIVIDEND,
            recipient=InvestReturn.Recipient.INVESTOR,
            confirmed=confirmed,
            created_by=self.admin,
        )

    def test_dispatches_once_on_confirmation_after_commit(self):
        invest_return = self._make_return()

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            invest_return.confirmed = True
            invest_return.save(update_fields=["confirmed"])
            # До коммита обработчик не вызывается.
            self.handler.assert_not_called()

        self.assertEqual(len(callbacks), 1)
        self.handler.assert_called_once()
        self.assertEqual(self.handler.call_args.kwargs["invest_return"].pk, invest_return.pk)

    def test_full_save_with_confirmation_dispatches(self):
        invest_return = self._make_return()

        with self.captureOnCommitCallbacks(execute=True):
            invest_return.confirmed = True
            invest_return.save()

        self.handler.assert_called_once()

    def test_created_already_confirmed_does_not_dispatch(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._make_return(confirmed=True)

        self.handler.assert_not_called()

    def test_resave_of_confirmed_return_does_not_dispatch(self):
        invest_return = self._make_return()
        with self.captureOnCommitCallbacks(execute=True):
            invest_return.confirmed = True
            invest_return.save(update_fields=["confirmed"])
        self.handler.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            invest_return.comment = "правка"
            invest_return.save()

        self.handler.assert_not_called()

    def test_save_without_confirmed_in_update_fields_does_not_dispatch(self):
        invest_return = self._make_return()

        with self.captureOnCommitCallbacks(execute=True):
            invest_return.confirmed = True
            invest_return.save(update_fields=["comment"])

        self.handler.assert_not_called()

    def test_unconfirm_does_not_dispatch(self):
        invest_return = self._make_return()
        with self.captureOnCommitCallbacks(execute=True):
            invest_return.confirmed = True
            invest_return.save(update_fields=["confirmed"])
        self.handler.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            invest_return.confirmed = False
            invest_return.save(update_fields=["confirmed"])

        self.handler.assert_not_called()

    def test_failing_handler_does_not_break_confirmation(self):
        self.handler.side_effect = RuntimeError("n8n down")
        invest_return = self._make_return()

        with self.captureOnCommitCallbacks(execute=True):
            invest_return.confirmed = True
            invest_return.save(update_fields=["confirmed"])

        invest_return.refresh_from_db()
        self.assertTrue(invest_return.confirmed)
        self.handler.assert_called_once()

    @patch("apps.modules.investments.approval_services.refresh_invest_return_approval_messages", return_value=0)
    def test_approval_chain_completion_dispatches(self, _refresh):
        invest_return = self._make_return()
        InvestmentReturnApproval.objects.create(
            tenant=self.tenant,
            invest_return=invest_return,
            step=1,
            step_type=InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
            approver_user=self.admin,
            decision=InvestmentReturnApproval.DECISION_APPROVED,
        )

        with self.captureOnCommitCallbacks(execute=True):
            route_invest_return_approvals(invest_return=invest_return)

        invest_return.refresh_from_db()
        self.assertTrue(invest_return.confirmed)
        self.handler.assert_called_once()
