"""Web Push hooks on approval changes (route_* decorators, PAYED/REJECTED, delete) and the cron command.

Hooks only mark subscriptions; `_flush()` runs the per-minute cron pass that sends.
"""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.modules.investments import approval_events as investment_approval_events
from apps.modules.investments.approval_services import confirm_invest_return_approval_by_id
from apps.modules.investments.models import (
    InvestmentApprovalConfigStep,
    InvestmentProjectApprovalConfigStep,
    InvestmentReturnApproval,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.investments.project_investment_approval_services import confirm_project_investment_approval_by_id
from apps.modules.notifications import push_services, signals
from apps.modules.notifications.models import ActionItemPushState, PushSubscription
from apps.modules.requests import approval_events as request_approval_events
from apps.modules.requests import status_events
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import (
    _recalculate_request_status,
    confirm_approval_by_id,
    route_request_approvals,
)
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
)
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

WEBPUSH = "apps.modules.notifications.push_services.webpush"
TG_SEND = "apps.modules.telegram_approvals.services.TelegramDispatcher.send"
VAPID = {"VAPID_PUBLIC_KEY": "test-public-key", "VAPID_PRIVATE_KEY": "test-private-key", "VAPID_SUBJECT": "mailto:t@example.com"}
NO_VAPID = {"VAPID_PUBLIC_KEY": "", "VAPID_PRIVATE_KEY": "", "VAPID_SUBJECT": ""}


def _endpoint(user):
    return f"https://fcm.googleapis.com/fcm/send/{user.username}"


def _subscribe(user):
    return PushSubscription.objects.create(
        user=user,
        endpoint=_endpoint(user),
        endpoint_hash=push_services.endpoint_hash(_endpoint(user)),
        p256dh="p256dh-secret",
        auth="auth-secret",
    )


def _pushed_endpoints(webpush_mock):
    return [call.kwargs["subscription_info"]["endpoint"] for call in webpush_mock.call_args_list]


def _flush():
    """The `* * * * *` cron run: sync users marked by hooks."""
    out = StringIO()
    call_command("sync_action_item_push", "--requested-only", stdout=out)
    return out.getvalue()


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", **VAPID)
class RequestPushHooksTests(TestCase):
    """Step 1: first + first_bis (serial), step 2: second, step 3: payer (payment)."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Hooks", subdomain="hooks-push", is_active=True)
        self.first = User.objects.create_user(username="hp-first", password="x", telegram_chat_id=501, telegram_from_id=601)
        self.first_bis = User.objects.create_user(username="hp-first-bis", password="x", telegram_chat_id=502)
        self.second = User.objects.create_user(username="hp-second", password="x", telegram_chat_id=503)
        self.payer = User.objects.create_user(username="hp-payer", password="x", telegram_chat_id=504)
        users = (self.first, self.first_bis, self.second, self.payer)
        for user in users:
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
            _subscribe(user)
        cfg = RequestApprovalConfig.objects.create(tenant=self.tenant)
        pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=cfg, payment_type=Request.PAYMENT_TYPE_CASH, is_enabled=True
        )
        for step, approvers, step_type in (
            (1, (self.first, self.first_bis), Approval.STEP_TYPE_SERIAL),
            (2, (self.second,), Approval.STEP_TYPE_SERIAL),
            (3, (self.payer,), Approval.STEP_TYPE_PAYMENT),
        ):
            step_cfg = RequestApprovalStepConfig.objects.create(
                payment_type_config=pt, step=step, is_enabled=True, step_type=step_type
            )
            for approver in approvers:
                RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=approver)
        self.req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.first,
            requester=self.first,
            title="t",
            amount=Decimal("100.00"),
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_CASH,
            status=Request.STATUS_DRAFT,
            billing_date=timezone.localdate(),
        )
        create_approval_rows_for_request(self.req)
        _recalculate_request_status(self.req)

        tg_patcher = patch(TG_SEND, return_value=None)
        self.tg_send = tg_patcher.start()
        self.addCleanup(tg_patcher.stop)
        webpush_patcher = patch(WEBPUSH)
        self.webpush = webpush_patcher.start()
        self.addCleanup(webpush_patcher.stop)

        with self.captureOnCommitCallbacks(execute=True):
            route_request_approvals(request_obj=self.req)
        _flush()
        self.tag = push_services.push_tag(subdomain=self.tenant.subdomain, kind="request", object_id=self.req.id)

    def _state(self, user):
        return ActionItemPushState.objects.get(user=user, tag=self.tag)

    def _approval(self, user, step):
        return Approval.objects.get(request=self.req, approver_user=user, step=step)

    def test_handlers_are_registered_in_ready(self):
        self.assertIn(signals.on_approvals_changed, request_approval_events.REQUEST_APPROVALS_CHANGED_HANDLERS)
        self.assertIn(signals.on_approvals_changed, investment_approval_events.INVESTMENT_APPROVALS_CHANGED_HANDLERS)
        self.assertIn(signals.on_request_payed, status_events.REQUEST_PAYED_EVENT_HANDLERS)
        self.assertIn(signals.on_request_rejected, status_events.REQUEST_REJECTED_EVENT_HANDLERS)

    def test_route_notifies_current_step_approvers(self):
        self.assertEqual(sorted(_pushed_endpoints(self.webpush)), sorted([_endpoint(self.first), _endpoint(self.first_bis)]))
        self.assertIsNone(self._state(self.first).closed_at)

    def test_portal_confirm_moves_push_to_next_step(self):
        self.webpush.reset_mock()
        for user in (self.first, self.first_bis):
            with self.captureOnCommitCallbacks(execute=True):
                confirm_approval_by_id(
                    tenant=self.tenant, approval_id=self._approval(user, 1).id, approver_user_id=user.id
                )
        _flush()

        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_PROGRESS_2)
        self.assertIsNotNone(self._state(self.first).closed_at)
        self.assertIsNotNone(self._state(self.first_bis).closed_at)
        self.assertIsNone(self._state(self.second).closed_at)
        self.assertEqual(_pushed_endpoints(self.webpush), [_endpoint(self.second)])

    def test_decision_request_only_marks_users_and_cron_sends(self):
        self.webpush.reset_mock()
        for user in (self.first, self.first_bis):
            with self.captureOnCommitCallbacks(execute=True):
                confirm_approval_by_id(
                    tenant=self.tenant, approval_id=self._approval(user, 1).id, approver_user_id=user.id
                )

        # Nothing is sent in the thread of the decision; the next step's approver is marked.
        self.webpush.assert_not_called()
        second_subscription = PushSubscription.objects.get(user=self.second)
        self.assertIsNotNone(second_subscription.sync_requested_at)

        output = _flush()

        self.assertEqual(_pushed_endpoints(self.webpush), [_endpoint(self.second)])
        self.assertIn("mode=requested", output)
        self.assertFalse(PushSubscription.objects.filter(sync_requested_at__isnull=False).exists())
        self.webpush.reset_mock()
        _flush()
        self.webpush.assert_not_called()

    def test_telegram_confirm_goes_through_route_and_closes_state(self):
        self.webpush.reset_mock()
        with patch.object(
            request_approval_events,
            "dispatch_request_approvals_changed",
            wraps=request_approval_events.dispatch_request_approvals_changed,
        ) as dispatch, self.captureOnCommitCallbacks(execute=True):
            confirm_approval_by_id(
                tenant=self.tenant,
                approval_id=self._approval(self.first, 1).id,
                request_id=self.req.id,
                approver_recipient_id="501",
                approver_external_user_id=601,
                decision=Approval.DECISION_APPROVED,
            )
        _flush()

        # confirm_approval_by_id has no decorator of its own: the event comes from route_request_approvals.
        dispatch.assert_called_with(tenant_id=self.tenant.id, kind="request", object_id=self.req.id)
        self.assertIsNotNone(self._state(self.first).closed_at)
        self.assertIsNone(self._state(self.first_bis).closed_at)  # step 1 still waits on first_bis
        self.webpush.assert_not_called()

    def test_early_return_on_rejected_and_payed_still_dispatches(self):
        for status in (Request.STATUS_REJECTED, Request.STATUS_PAYED):
            Request.all_objects.filter(pk=self.req.pk).update(status=status)
            self.req.refresh_from_db()
            with self.subTest(status=status), patch.object(
                request_approval_events, "dispatch_request_approvals_changed"
            ) as dispatch, self.captureOnCommitCallbacks(execute=True):
                route_request_approvals(request_obj=self.req)
            dispatch.assert_called_once_with(tenant_id=self.tenant.id, kind="request", object_id=self.req.id)

    def test_dispatch_waits_for_commit(self):
        with patch.object(request_approval_events, "dispatch_request_approvals_changed") as dispatch, \
                self.captureOnCommitCallbacks(execute=False) as callbacks:
            route_request_approvals(request_obj=self.req)
            dispatch.assert_not_called()
        self.assertGreaterEqual(len(callbacks), 1)

    def test_rejection_closes_state_for_everyone(self):
        self.webpush.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            confirm_approval_by_id(
                tenant=self.tenant,
                approval_id=self._approval(self.first, 1).id,
                approver_user_id=self.first.id,
                decision=Approval.DECISION_REJECTED,
            )
        _flush()

        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_REJECTED)
        self.assertIsNotNone(self._state(self.first).closed_at)
        self.assertIsNotNone(self._state(self.first_bis).closed_at)
        self.webpush.assert_not_called()

    def test_payed_closes_payment_state(self):
        for user, step in ((self.first, 1), (self.first_bis, 1), (self.second, 2)):
            with self.captureOnCommitCallbacks(execute=True):
                confirm_approval_by_id(tenant=self.tenant, approval_id=self._approval(user, step).id, approver_user_id=user.id)
            _flush()
        self.assertIsNone(self._state(self.payer).closed_at)

        with self.captureOnCommitCallbacks(execute=True):
            confirm_approval_by_id(
                tenant=self.tenant, approval_id=self._approval(self.payer, 3).id, approver_user_id=self.payer.id
            )
        _flush()

        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_PAYED)
        self.assertIsNotNone(self._state(self.payer).closed_at)

    def test_delete_request_closes_state(self):  # p.21
        with self.captureOnCommitCallbacks(execute=True):
            Request.all_objects.get(pk=self.req.pk).delete()
        _flush()

        self.assertIsNotNone(self._state(self.first).closed_at)
        self.assertIsNotNone(self._state(self.first_bis).closed_at)

    def test_push_failure_keeps_decision_and_telegram(self):  # p.23
        self.webpush.side_effect = RuntimeError("push service down")
        self.tg_send.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            confirm_approval_by_id(tenant=self.tenant, approval_id=self._approval(self.first, 1).id, approver_user_id=self.first.id)
            confirm_approval_by_id(
                tenant=self.tenant, approval_id=self._approval(self.first_bis, 1).id, approver_user_id=self.first_bis.id
            )
        with self.assertLogs("apps.modules.notifications.push_services", level="ERROR"):
            _flush()

        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.STATUS_PROGRESS_2)
        self.assertEqual(self._approval(self.first, 1).decision, Approval.DECISION_APPROVED)
        sent_approval_ids = {call.kwargs.get("approval_id") for call in self.tg_send.call_args_list}
        self.assertIn(self._approval(self.second, 2).id, sent_approval_ids)
        self.assertIsNone(PushSubscription.objects.get(user=self.second).revoked_at)

    def test_handler_failure_does_not_break_route(self):
        with patch.object(signals.push_services, "request_sync_for_object", side_effect=RuntimeError("boom")), \
                self.assertLogs("apps.modules.requests.approval_events", level="ERROR"), \
                self.captureOnCommitCallbacks(execute=True):
            confirm_approval_by_id(tenant=self.tenant, approval_id=self._approval(self.first, 1).id, approver_user_id=self.first.id)

        self.assertEqual(self._approval(self.first, 1).decision, Approval.DECISION_APPROVED)

    @override_settings(**NO_VAPID)
    def test_without_vapid_hooks_do_nothing(self):  # p.23
        self.webpush.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            confirm_approval_by_id(tenant=self.tenant, approval_id=self._approval(self.first, 1).id, approver_user_id=self.first.id)
            Request.all_objects.get(pk=self.req.pk).delete()
        _flush()

        self.webpush.assert_not_called()
        self.assertFalse(PushSubscription.objects.filter(sync_requested_at__isnull=False).exists())
        self.assertIsNone(self._state(self.first).closed_at)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", **VAPID)
class InvestmentPushHooksTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Invest", subdomain="invest-push", is_active=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)
        self.first = User.objects.create_user(username="ip-first", password="x")
        self.second = User.objects.create_user(username="ip-second", password="x")
        for user in (self.first, self.second):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
            TenantUserRole.objects.create(tenant=self.tenant, user=user, role=TenantUserRole.ROLE_INVESTOR)
            _subscribe(user)
        self.invest_return = InvestReturn.objects.create(
            tenant=self.tenant,
            date=date(2026, 11, 1),
            billing_date=date(2026, 11, 1),
            sum=Decimal("1200.00"),
            currency="USD",
            type=InvestReturn.ReturnType.DIVIDEND,
            recipient=InvestReturn.Recipient.INVESTOR,
            created_by=self.first,
        )
        self.approvals = {
            user: InvestmentReturnApproval.objects.create(
                tenant=self.tenant,
                invest_return=self.invest_return,
                step=step,
                step_type=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                approver_user=user,
                decision=InvestmentReturnApproval.DECISION_PENDING,
            )
            for step, user in ((1, self.first), (2, self.second))
        }
        tg_patcher = patch(TG_SEND, return_value=None)
        tg_patcher.start()
        self.addCleanup(tg_patcher.stop)
        webpush_patcher = patch(WEBPUSH)
        self.webpush = webpush_patcher.start()
        self.addCleanup(webpush_patcher.stop)
        push_services.sync_user_action_item_push(user=self.first)
        self.tag = push_services.push_tag(
            subdomain=self.tenant.subdomain, kind="invest_return", object_id=self.invest_return.id
        )

    def test_confirm_syncs_through_route(self):
        self.assertEqual(_pushed_endpoints(self.webpush), [_endpoint(self.first)])
        self.webpush.reset_mock()

        with patch.object(
            investment_approval_events,
            "dispatch_investment_approvals_changed",
            wraps=investment_approval_events.dispatch_investment_approvals_changed,
        ) as dispatch, self.captureOnCommitCallbacks(execute=True):
            confirm_invest_return_approval_by_id(
                tenant=self.tenant,
                approval_id=self.approvals[self.first].id,
                decision=InvestmentReturnApproval.DECISION_APPROVED,
            )
        _flush()

        dispatch.assert_called_with(tenant_id=self.tenant.id, kind="invest_return", object_id=self.invest_return.id)
        self.assertIsNotNone(ActionItemPushState.objects.get(user=self.first, tag=self.tag).closed_at)
        self.assertEqual(_pushed_endpoints(self.webpush), [_endpoint(self.second)])

    def test_project_investment_confirm_syncs_through_route(self):
        project = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 11, 2),
            amount=Decimal("5000.00"),
            currency="USD",
            funding_method=ProjectInvestment.FundingMethod.CASH,
            created_by=self.first,
        )
        approvals = {
            user: ProjectInvestmentApproval.objects.create(
                tenant=self.tenant,
                project_investment=project,
                step=step,
                step_type=InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL,
                approver_user=user,
                decision=ProjectInvestmentApproval.DECISION_PENDING,
            )
            for step, user in ((1, self.first), (2, self.second))
        }
        tag = push_services.push_tag(subdomain=self.tenant.subdomain, kind="project_investment", object_id=project.id)
        self.webpush.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            push_services.sync_users_for_object(tenant=self.tenant, kind="project_investment", object_id=project.id)
        self.assertEqual(_pushed_endpoints(self.webpush), [_endpoint(self.first)])
        self.webpush.reset_mock()

        with patch.object(
            investment_approval_events,
            "dispatch_investment_approvals_changed",
            wraps=investment_approval_events.dispatch_investment_approvals_changed,
        ) as dispatch, self.captureOnCommitCallbacks(execute=True):
            confirm_project_investment_approval_by_id(
                tenant=self.tenant,
                approval_id=approvals[self.first].id,
                decision=ProjectInvestmentApproval.DECISION_APPROVED,
            )
        _flush()

        dispatch.assert_called_with(tenant_id=self.tenant.id, kind="project_investment", object_id=project.id)
        self.assertIsNotNone(ActionItemPushState.objects.get(user=self.first, tag=tag).closed_at)
        self.assertEqual(_pushed_endpoints(self.webpush), [_endpoint(self.second)])


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", **VAPID)
class SyncActionItemPushCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Cron", subdomain="cron-push", is_active=True)
        self.user = User.objects.create_user(username="cp-user", password="x")
        self.other = User.objects.create_user(username="cp-other", password="x")
        for user in (self.user, self.other):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        _subscribe(self.user)
        webpush_patcher = patch(WEBPUSH)
        self.webpush = webpush_patcher.start()
        self.addCleanup(webpush_patcher.stop)

    def _draft_with_pending_step(self):
        req = Request.all_objects.create(
            tenant=self.tenant,
            created_by=self.user,
            requester=self.user,
            title="t",
            amount=Decimal("10.00"),
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_CASH,
            status=Request.STATUS_PROGRESS_1,
            billing_date=timezone.localdate(),
        )
        Approval.objects.create(request=req, approver_user=self.user, step=1, step_type=Approval.STEP_TYPE_SERIAL)
        return req

    def _run(self, *args):
        out = StringIO()
        call_command("sync_action_item_push", *args, stdout=out)
        return out.getvalue()

    def test_closes_state_of_request_deleted_by_bulk_update(self):
        req = self._draft_with_pending_step()
        self._run()
        self.assertEqual(self.webpush.call_count, 1)
        tag = push_services.push_tag(subdomain=self.tenant.subdomain, kind="request", object_id=req.id)
        Request.all_objects.filter(pk=req.pk).update(status=Request.STATUS_DELETED)

        with self.assertLogs("apps.modules.notifications.management.commands.sync_action_item_push", level="INFO") as logs:
            self._run()

        self.assertIsNotNone(ActionItemPushState.objects.get(user=self.user, tag=tag).closed_at)
        self.assertEqual(self.webpush.call_count, 1)
        self.assertTrue(any("users=1" in line and "duration=" in line for line in logs.output))

    def test_max_users_limits_the_run(self):
        _subscribe(self.other)
        with patch.object(push_services, "sync_user_action_item_push", return_value=0) as sync:
            output = self._run("--max-users", "1")

        self.assertEqual(sync.call_count, 1)
        self.assertEqual(sync.call_args.kwargs["user"].id, min(self.user.id, self.other.id))
        self.assertIn("users=1", output)

    def test_max_users_takes_longest_unsynced_users_first(self):
        _subscribe(self.other)
        first, second = sorted([self.user, self.other], key=lambda u: u.id)
        PushSubscription.objects.filter(user=first).update(synced_at=timezone.now())
        with patch.object(push_services, "sync_user_action_item_push", return_value=0) as sync:
            self._run("--max-users", "1")

        self.assertEqual(sync.call_args.kwargs["user"].id, second.id)

    def test_consecutive_limited_runs_cover_every_user(self):
        _subscribe(self.other)
        self._run("--max-users", "1")
        self._run("--max-users", "1")

        self.assertFalse(PushSubscription.objects.filter(revoked_at__isnull=True, synced_at__isnull=True).exists())

    def test_max_seconds_stops_starting_new_users(self):
        _subscribe(self.other)
        command_time = "apps.modules.notifications.management.commands.sync_action_item_push.monotonic"
        with patch(command_time, side_effect=[0.0, 0.0, 100.0, 100.0]), patch.object(
            push_services, "sync_user_action_item_push", return_value=0
        ) as sync, self.assertLogs(
            "apps.modules.notifications.management.commands.sync_action_item_push", level="WARNING"
        ):
            output = self._run("--max-seconds", "10")

        self.assertEqual(sync.call_count, 1)
        self.assertIn("users=1", output)

    def test_requested_only_syncs_marked_users(self):
        _subscribe(self.other)
        push_services.request_sync_for_users([self.other.id])
        with patch.object(push_services, "sync_user_action_item_push", return_value=0) as sync:
            output = self._run("--requested-only")

        self.assertEqual([call.kwargs["user"].id for call in sync.call_args_list], [self.other.id])
        self.assertIn("mode=requested users=1", output)

    def test_inactive_user_subscription_is_revoked_by_catch_up(self):
        self._draft_with_pending_step()
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        self._run()

        self.webpush.assert_not_called()
        subscription = PushSubscription.objects.get(user=self.user)
        self.assertEqual(subscription.revoke_reason, PushSubscription.REVOKE_REASON_INACTIVE)

    def test_user_with_open_state_and_no_subscription_is_synced(self):
        req = self._draft_with_pending_step()
        ActionItemPushState.objects.create(
            tenant=self.tenant,
            user=self.other,
            tag=push_services.push_tag(subdomain=self.tenant.subdomain, kind="request", object_id=req.id),
            sent_at=timezone.now(),
        )

        self._run()

        self.assertIsNotNone(ActionItemPushState.objects.get(user=self.other).closed_at)

    def test_failing_user_is_counted_and_others_continue(self):
        _subscribe(self.other)
        with patch.object(push_services, "sync_user_action_item_push", side_effect=[RuntimeError("boom"), 0]), \
                self.assertLogs("apps.modules.notifications.management.commands.sync_action_item_push", level="ERROR"):
            output = self._run()

        self.assertIn("users=2", output)
        self.assertIn("errors=1", output)

    @override_settings(**NO_VAPID)
    def test_without_vapid_exits_immediately(self):
        self._draft_with_pending_step()
        with patch.object(push_services, "sync_user_action_item_push") as sync:
            output = self._run()

        sync.assert_not_called()
        self.assertIn("Web Push is off", output)
        self.assertFalse(ActionItemPushState.objects.exists())
