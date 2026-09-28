"""
Tests for `redispatch_unsent_approval_cards`.

Regression context (tenant neuron, 2026-09-18/19): a newly added approver had not started
the Telegram bot, so the gateway refused his cards. `dispatch_pending_approvals` skipped him
silently, the approval stayed pending without a card, and nothing retried it — 17 requests
sat on that one approver. The command re-runs routing for exactly those requests.
"""

from datetime import date, datetime
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.modules.requests.approval_redispatch import find_requests_with_unsent_approvals
from apps.modules.requests.approval_workflow import route_request_approvals
from apps.modules.requests.models import Approval, Request, RequestComment
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.tenants.models import Tenant

User = get_user_model()

COMMAND = "redispatch_unsent_approval_cards"


def _at_noon(d: date):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


class _GatewayResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"message_id": 777}
        self.content = b"{}"

    def json(self):
        return self._payload


@override_settings(BASE_DOMAIN="example.com", MESSAGING_GATEWAY_SEND_URL="http://gw.example/v1/messaging/send")
class RedispatchUnsentApprovalCardsCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="redispatch-a", is_active=True)
        self.other_tenant = Tenant.objects.create(name="Other", subdomain="redispatch-b", is_active=True)

        # The system account must be pk=1 (see _leave_system_comment).
        if not User.objects.filter(pk=1).exists():
            User.objects.create(pk=1, username="system-redispatch", full_name="Система")
        self.requester = User.objects.create_user(username="rd_requester", password="x")
        self.first_approver = User.objects.create_user(username="rd_first", password="x")
        self.second_approver = User.objects.create_user(username="rd_second", password="x")
        self.unstarted_approver = User.objects.create_user(username="rd_unstarted", password="x")
        self.payer = User.objects.create_user(username="rd_payer", password="x")

        self.mock_post = self._start_patch("apps.modules.telegram_approvals.services.requests.post")
        self.mock_post.return_value = _GatewayResponse()
        self._start_patch("apps.modules.telegram_approvals.services.build_approval_message", return_value="text")
        self._start_patch("apps.modules.telegram_approvals.services._buttons", return_value=[])

    def _start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _make_request(
        self,
        *,
        tenant=None,
        payment_type=Request.PAYMENT_TYPE_CASH,
        status=Request.STATUS_PROGRESS_2,
        submitted=date(2026, 9, 18),
    ):
        return Request.objects.create(
            tenant=tenant or self.tenant,
            created_by=self.requester,
            requester=self.requester,
            title="R",
            description="",
            amount=100,
            currency="UZS",
            payment_type=payment_type,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1),
            status=status,
            submitted_at=_at_noon(submitted),
        )

    def _add_approval(
        self,
        request_obj,
        user,
        *,
        step,
        decision=Approval.DECISION_PENDING,
        step_type=Approval.STEP_TYPE_SERIAL,
        sent=False,
        recipient="4242",
    ):
        message = None
        if sent:
            message = TelegramMessage.objects.create(
                tenant=request_obj.tenant, recipient_id=str(recipient), message_id=1, sent_at=timezone.now(),
            )
        return Approval.objects.create(
            request=request_obj,
            approver_user=user,
            approver_recipient_id=recipient,
            step=step,
            step_type=step_type,
            decision=decision,
            telegram_message=message,
        )

    def _stuck_request(self, **kwargs):
        """The neuron shape: step 2 has two approvers, one approved, the other never got a card."""
        request_obj = self._make_request(**kwargs)
        self._add_approval(request_obj, self.first_approver, step=1, decision=Approval.DECISION_APPROVED, sent=True)
        self._add_approval(request_obj, self.second_approver, step=2, decision=Approval.DECISION_APPROVED, sent=True)
        target = self._add_approval(request_obj, self.unstarted_approver, step=2)
        self._add_approval(request_obj, self.payer, step=3, step_type=Approval.STEP_TYPE_PAYMENT)
        return request_obj, target

    def _run(self, *args):
        out = StringIO()
        call_command(COMMAND, *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    # --- dry run -----------------------------------------------------------

    def test_dry_run_lists_stuck_request_and_sends_nothing(self):
        request_obj, target = self._stuck_request()

        output = self._run("--tenant", str(self.tenant.pk))

        self.assertIn(f"Request {request_obj.pk}", output)
        self.assertIn("rd_unstarted", output)
        self.assertIn("Dry run", output)
        self.mock_post.assert_not_called()
        target.refresh_from_db()
        self.assertIsNone(target.telegram_message_id)
        self.assertFalse(RequestComment.objects.filter(request=request_obj).exists())

    # --- apply -------------------------------------------------------------

    def test_apply_sends_card_to_unstarted_approver_and_leaves_system_comment(self):
        request_obj, target = self._stuck_request()

        self._run("--tenant", str(self.tenant.pk), "--apply")

        target.refresh_from_db()
        self.assertIsNotNone(target.telegram_message_id)
        self.assertEqual(target.decision, Approval.DECISION_PENDING)
        comment = RequestComment.objects.get(request=request_obj)
        self.assertEqual(comment.created_by_id, 1)
        self.assertIn("rd_unstarted", comment.body)

    def test_apply_does_not_send_cards_for_future_steps(self):
        request_obj, _target = self._stuck_request()

        self._run("--tenant", str(self.tenant.pk), "--apply")

        payment = Approval.objects.get(request=request_obj, step=3)
        self.assertIsNone(payment.telegram_message_id)

    def test_second_run_finds_nothing(self):
        self._stuck_request()
        self._run("--tenant", str(self.tenant.pk), "--apply")

        output = self._run("--tenant", str(self.tenant.pk), "--apply")

        self.assertIn("No requests with unsent approval cards found.", output)
        self.assertEqual(RequestComment.objects.count(), 1)

    def test_approved_request_dispatches_its_payment_step(self):
        request_obj = self._make_request(status=Request.STATUS_APPROVED)
        self._add_approval(request_obj, self.first_approver, step=1, decision=Approval.DECISION_APPROVED, sent=True)
        payment = self._add_approval(request_obj, self.payer, step=2, step_type=Approval.STEP_TYPE_PAYMENT)

        self._run("--tenant", str(self.tenant.pk), "--apply")

        payment.refresh_from_db()
        self.assertIsNotNone(payment.telegram_message_id)

    def test_gateway_refusal_keeps_card_unsent_and_fails_the_command(self):
        request_obj, target = self._stuck_request()
        self.mock_post.return_value = _GatewayResponse(status_code=403)

        with self.assertRaises(CommandError) as ctx:
            self._run("--tenant", str(self.tenant.pk), "--apply")

        self.assertIn("rd_unstarted", str(ctx.exception))
        target.refresh_from_db()
        self.assertIsNone(target.telegram_message_id)
        self.assertFalse(RequestComment.objects.filter(request=request_obj).exists())

    def test_routing_error_is_reported_and_does_not_stop_other_requests(self):
        broken, _ = self._stuck_request()
        healthy, healthy_target = self._stuck_request()

        def flaky(*, request_obj):
            if request_obj.pk == broken.pk:
                raise RuntimeError("boom")
            return route_request_approvals(request_obj=request_obj)

        with patch("apps.modules.requests.approval_redispatch.route_request_approvals", side_effect=flaky):
            with self.assertRaises(CommandError) as ctx:
                self._run("--tenant", str(self.tenant.pk), "--apply")

        self.assertIn(f"Request {broken.pk}", str(ctx.exception))
        healthy_target.refresh_from_db()
        self.assertIsNotNone(healthy_target.telegram_message_id)

    # --- filters -----------------------------------------------------------

    def test_tenant_filter_leaves_other_tenants_untouched(self):
        _mine, mine_target = self._stuck_request()
        _theirs, theirs_target = self._stuck_request(tenant=self.other_tenant)

        self._run("--tenant", str(self.tenant.pk), "--apply")

        mine_target.refresh_from_db()
        theirs_target.refresh_from_db()
        self.assertIsNotNone(mine_target.telegram_message_id)
        self.assertIsNone(theirs_target.telegram_message_id)

    def test_omitted_tenant_processes_all_tenants(self):
        _mine, mine_target = self._stuck_request()
        _theirs, theirs_target = self._stuck_request(tenant=self.other_tenant)

        self._run("--apply")

        mine_target.refresh_from_db()
        theirs_target.refresh_from_db()
        self.assertIsNotNone(mine_target.telegram_message_id)
        self.assertIsNotNone(theirs_target.telegram_message_id)

    def test_comma_separated_tenants(self):
        _mine, mine_target = self._stuck_request()
        _theirs, theirs_target = self._stuck_request(tenant=self.other_tenant)

        self._run("--tenant", f"{self.tenant.pk},{self.other_tenant.pk}", "--apply")

        mine_target.refresh_from_db()
        theirs_target.refresh_from_db()
        self.assertIsNotNone(mine_target.telegram_message_id)
        self.assertIsNotNone(theirs_target.telegram_message_id)

    def test_payment_type_filter(self):
        _cash, cash_target = self._stuck_request(payment_type=Request.PAYMENT_TYPE_CASH)
        _transfer, transfer_target = self._stuck_request(payment_type=Request.PAYMENT_TYPE_TRANSFER)

        self._run("--tenant", str(self.tenant.pk), "--payment-type", Request.PAYMENT_TYPE_TRANSFER, "--apply")

        cash_target.refresh_from_db()
        transfer_target.refresh_from_db()
        self.assertIsNone(cash_target.telegram_message_id)
        self.assertIsNotNone(transfer_target.telegram_message_id)

    def test_comma_separated_payment_types_with_spaces_in_names(self):
        _cash, cash_target = self._stuck_request(payment_type=Request.PAYMENT_TYPE_CASH)
        _card, card_target = self._stuck_request(payment_type=Request.PAYMENT_TYPE_CARD)
        _transfer, transfer_target = self._stuck_request(payment_type=Request.PAYMENT_TYPE_TRANSFER)

        self._run(
            "--tenant", str(self.tenant.pk),
            "--payment-type", f"{Request.PAYMENT_TYPE_CASH},{Request.PAYMENT_TYPE_CARD}",
            "--apply",
        )

        for target in (cash_target, card_target, transfer_target):
            target.refresh_from_db()
        self.assertIsNotNone(cash_target.telegram_message_id)
        self.assertIsNotNone(card_target.telegram_message_id)
        self.assertIsNone(transfer_target.telegram_message_id)

    def test_date_range_filter_is_inclusive_by_submission_date(self):
        _before, before_target = self._stuck_request(submitted=date(2026, 9, 17))
        _first, first_target = self._stuck_request(submitted=date(2026, 9, 18))
        _last, last_target = self._stuck_request(submitted=date(2026, 9, 19))
        _after, after_target = self._stuck_request(submitted=date(2026, 9, 20))

        self._run(
            "--tenant", str(self.tenant.pk), "--date-from", "2026-09-18", "--date-to", "2026-09-19", "--apply",
        )

        targets = [before_target, first_target, last_target, after_target]
        for target in targets:
            target.refresh_from_db()
        self.assertEqual(
            [t.telegram_message_id is not None for t in targets],
            [False, True, True, False],
        )

    # --- what is *not* a stuck card ---------------------------------------

    def test_ignores_requests_that_are_not_waiting_and_approvals_without_recipient(self):
        for status in (Request.STATUS_PAYED, Request.STATUS_REJECTED, Request.STATUS_DRAFT):
            request_obj = self._make_request(status=status)
            self._add_approval(request_obj, self.unstarted_approver, step=2)

        no_recipient = self._make_request()
        self._add_approval(no_recipient, self.unstarted_approver, step=2, recipient=None)

        self.assertEqual(find_requests_with_unsent_approvals(), [])

    def test_ignores_request_whose_only_unsent_approval_is_on_a_future_step(self):
        request_obj = self._make_request(status=Request.STATUS_PROGRESS_1)
        self._add_approval(request_obj, self.first_approver, step=1, sent=True)
        self._add_approval(request_obj, self.payer, step=3, step_type=Approval.STEP_TYPE_PAYMENT)

        self.assertEqual(find_requests_with_unsent_approvals(), [])

    # --- argument validation ----------------------------------------------

    def test_rejects_unknown_tenant(self):
        with self.assertRaises(CommandError):
            self._run("--tenant", "999999")

    def test_rejects_non_numeric_tenant(self):
        with self.assertRaises(CommandError):
            self._run("--tenant", "neuron")

    def test_rejects_unknown_payment_type(self):
        with self.assertRaises(CommandError):
            self._run("--payment-type", "Криптовалюта")

    def test_rejects_malformed_date(self):
        with self.assertRaises(CommandError):
            self._run("--date-from", "18.09.2026")

    def test_rejects_inverted_date_range(self):
        with self.assertRaises(CommandError):
            self._run("--date-from", "2026-09-19", "--date-to", "2026-09-18")
