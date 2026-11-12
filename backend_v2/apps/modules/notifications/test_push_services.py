"""Web Push sending and sync of action items (pywebpush.webpush is mocked)."""

import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from pywebpush import WebPushException

from apps.modules.notifications import push_services, services
from apps.modules.notifications.models import ActionItemPushState, PushSubscription
from apps.modules.requests.models import Approval, Request
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()

WEBPUSH = "apps.modules.notifications.push_services.webpush"
VAPID = {"VAPID_PUBLIC_KEY": "test-public-key", "VAPID_PRIVATE_KEY": "test-private-key", "VAPID_SUBJECT": "mailto:t@example.com"}
NO_VAPID = {"VAPID_PUBLIC_KEY": "", "VAPID_PRIVATE_KEY": "", "VAPID_SUBJECT": ""}


class PushFixturesMixin:
    def make_fixtures(self):
        self.acme = Tenant.objects.create(name="Acme", subdomain="acme-ps", is_active=True)
        self.beta = Tenant.objects.create(name="Beta", subdomain="beta-ps", is_active=True)
        self.user = User.objects.create_user(username="ps-user", password="x")
        self.next_user = User.objects.create_user(username="ps-next", password="x")
        for tenant in (self.acme, self.beta):
            TenantMembership.objects.create(tenant=tenant, user=self.user, is_active=True)
        TenantMembership.objects.create(tenant=self.acme, user=self.next_user, is_active=True)

    def subscribe(self, user=None, n=1):
        user = user or self.user
        endpoint = f"https://fcm.googleapis.com/fcm/send/{user.username}-{n}"
        return PushSubscription.objects.create(
            user=user,
            endpoint=endpoint,
            endpoint_hash=push_services.endpoint_hash(endpoint),
            p256dh=f"p256dh-secret-{n}",
            auth=f"auth-secret-{n}",
        )

    def pending_request(self, tenant, *, user=None, status=Request.STATUS_PROGRESS_1, step=1, purpose=""):
        req = Request.all_objects.create(
            tenant=tenant,
            created_by=self.user,
            requester=self.user,
            title="Закупка",
            payment_purpose=purpose,
            amount=Decimal("1500.50"),
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_CASH,
            status=status,
            billing_date=timezone.localdate(),
        )
        Approval.objects.create(request=req, approver_user=user or self.user, step=step, step_type=Approval.STEP_TYPE_SERIAL)
        return req

    def tag(self, tenant, req):
        return push_services.push_tag(subdomain=tenant.subdomain, kind="request", object_id=req.id)

    @staticmethod
    def payloads(webpush_mock):
        return [json.loads(call.kwargs["data"]) for call in webpush_mock.call_args_list]


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", **VAPID)
class SyncUserActionItemPushTests(PushFixturesMixin, TestCase):
    def setUp(self):
        self.make_fixtures()

    @patch(WEBPUSH)
    def test_one_push_per_device_with_company_title_and_amount(self, webpush):  # p.20
        self.subscribe(n=1)
        self.subscribe(n=2)
        req = self.pending_request(self.acme, purpose="Аренда офиса")

        sent = push_services.sync_user_action_item_push(user=self.user)

        self.assertEqual(sent, 2)
        self.assertEqual(webpush.call_count, 2)
        payload = self.payloads(webpush)[0]
        tag = f"acme-ps:request-{req.id}"
        self.assertEqual(
            payload,
            {
                "type": "show",
                "tag": tag,
                "title": f"Acme: Заявка #{req.id} · Аренда офиса",
                "body": "1 500.50 UZS",
                "url": f"/app/requests/{req.id}?company=acme-ps",
                "count": 1,
                "active_tags": [tag],
            },
        )
        call = webpush.call_args_list[0].kwargs
        self.assertEqual(call["ttl"], 86400)
        self.assertEqual(call["timeout"], 3)
        self.assertIsInstance(call["requests_session"], push_services._NoRedirectSession)
        self.assertEqual(call["vapid_claims"], {"sub": "mailto:t@example.com"})
        state = ActionItemPushState.objects.get(user=self.user, tag=tag)
        self.assertEqual(state.tenant_id, self.acme.id)
        self.assertIsNone(state.closed_at)
        self.assertEqual(PushSubscription.objects.filter(last_success_at__isnull=False).count(), 2)

    @patch(WEBPUSH)
    def test_repeated_sync_sends_nothing(self, webpush):
        self.subscribe()
        self.pending_request(self.acme)
        push_services.sync_user_action_item_push(user=self.user)
        webpush.reset_mock()

        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        webpush.assert_not_called()

    @patch(WEBPUSH)
    def test_closed_step_only_closes_state_and_next_show_drops_its_tag(self, webpush):  # p.21
        self.subscribe()
        first = self.pending_request(self.acme)
        push_services.sync_user_action_item_push(user=self.user)
        Approval.objects.filter(request=first).update(decision=Approval.DECISION_APPROVED)
        webpush.reset_mock()

        push_services.sync_user_action_item_push(user=self.user)

        webpush.assert_not_called()
        self.assertIsNotNone(ActionItemPushState.objects.get(tag=self.tag(self.acme, first)).closed_at)

        second = self.pending_request(self.acme)
        push_services.sync_user_action_item_push(user=self.user)

        self.assertEqual(webpush.call_count, 1)
        payload = self.payloads(webpush)[0]
        self.assertEqual(payload["active_tags"], [self.tag(self.acme, second)])
        self.assertEqual(payload["count"], 1)

    @patch(WEBPUSH)
    def test_step_reopened_on_same_object_is_pushed_again(self, webpush):
        self.subscribe()
        req = self.pending_request(self.acme)
        push_services.sync_user_action_item_push(user=self.user)
        Approval.objects.filter(request=req).update(decision=Approval.DECISION_APPROVED)
        push_services.sync_user_action_item_push(user=self.user)
        Approval.objects.create(request=req, approver_user=self.user, step=1, step_type=Approval.STEP_TYPE_SERIAL)
        webpush.reset_mock()

        push_services.sync_user_action_item_push(user=self.user)

        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(ActionItemPushState.objects.filter(tag=self.tag(self.acme, req)).count(), 1)
        self.assertIsNone(ActionItemPushState.objects.get(tag=self.tag(self.acme, req)).closed_at)

    @patch(WEBPUSH)
    def test_two_companies_one_push_per_item_with_total_count(self, webpush):
        self.subscribe()
        acme_req = self.pending_request(self.acme)
        beta_req = self.pending_request(self.beta)

        push_services.sync_user_action_item_push(user=self.user)

        payloads = self.payloads(webpush)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(
            sorted(p["title"].split(":")[0] for p in payloads),
            ["Acme", "Beta"],
        )
        self.assertEqual({p["count"] for p in payloads}, {2})
        expected_tags = sorted([self.tag(self.acme, acme_req), self.tag(self.beta, beta_req)])
        self.assertEqual({tuple(p["active_tags"]) for p in payloads}, {tuple(expected_tags)})
        beta_payload = next(p for p in payloads if p["title"].startswith("Beta"))
        self.assertEqual(beta_payload["url"], f"/app/requests/{beta_req.id}?company=beta-ps")

    @patch(WEBPUSH)
    def test_lost_membership_drops_company_items_and_keeps_subscription(self, webpush):
        subscription = self.subscribe()
        acme_req = self.pending_request(self.acme)
        beta_req = self.pending_request(self.beta)
        push_services.sync_user_action_item_push(user=self.user)
        TenantMembership.objects.filter(tenant=self.beta, user=self.user).update(is_active=False)
        webpush.reset_mock()

        new_req = self.pending_request(self.acme)
        push_services.sync_user_action_item_push(user=self.user)

        subscription.refresh_from_db()
        self.assertIsNone(subscription.revoked_at)
        self.assertEqual(webpush.call_count, 1)
        payload = self.payloads(webpush)[0]
        self.assertEqual(payload["active_tags"], sorted([self.tag(self.acme, acme_req), self.tag(self.acme, new_req)]))
        self.assertEqual(payload["count"], 2)
        self.assertIsNotNone(ActionItemPushState.objects.get(tag=self.tag(self.beta, beta_req)).closed_at)

    @patch(WEBPUSH)
    def test_revoked_subscription_gets_nothing(self, webpush):
        subscription = self.subscribe()
        subscription.revoked_at = timezone.now()
        subscription.save(update_fields=["revoked_at"])
        self.pending_request(self.acme)

        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        webpush.assert_not_called()
        self.assertFalse(ActionItemPushState.objects.exists())

    @override_settings(**NO_VAPID)
    @patch(WEBPUSH)
    def test_without_vapid_nothing_is_sent(self, webpush):  # p.23
        self.subscribe()
        req = self.pending_request(self.acme)

        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        self.assertEqual(
            push_services.sync_users_for_object(tenant=self.acme, kind="request", object_id=req.id), 0
        )
        webpush.assert_not_called()
        self.assertFalse(ActionItemPushState.objects.exists())

    @patch(WEBPUSH)
    def test_same_user_on_next_step_of_same_object_is_pushed_again(self, webpush):
        self.subscribe()
        req = self.pending_request(self.acme)
        Approval.objects.create(request=req, approver_user=self.user, step=2, step_type=Approval.STEP_TYPE_SERIAL)
        push_services.sync_user_action_item_push(user=self.user)
        self.assertEqual(webpush.call_count, 1)
        webpush.reset_mock()
        Approval.objects.filter(request=req, step=1).update(decision=Approval.DECISION_APPROVED)
        Request.all_objects.filter(pk=req.pk).update(status=Request.STATUS_PROGRESS_2)

        push_services.sync_users_for_object(tenant=self.acme, kind="request", object_id=req.id)

        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(self.payloads(webpush)[0]["tag"], self.tag(self.acme, req))
        state = ActionItemPushState.objects.get(user=self.user, tag=self.tag(self.acme, req))
        step2 = Approval.objects.get(request=req, step=2)
        self.assertEqual(state.step_key, f"2:{step2.id}")
        self.assertIsNone(state.closed_at)
        webpush.reset_mock()
        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        webpush.assert_not_called()

    @patch(WEBPUSH)
    def test_failed_company_collection_keeps_its_items_open_and_does_not_push_them_again(self, webpush):
        self.subscribe()
        acme_req = self.pending_request(self.acme)
        push_services.sync_user_action_item_push(user=self.user)
        webpush.reset_mock()
        beta_req = self.pending_request(self.beta)
        real_provider = services.list_request_action_items

        def failing_in_acme(*, tenant, user):
            if tenant.id == self.acme.id:
                raise RuntimeError("db hiccup")
            return real_provider(tenant=tenant, user=user)

        with patch.object(services, "list_request_action_items", side_effect=failing_in_acme), self.assertLogs(
            "apps.modules.notifications.services", level="ERROR"
        ):
            push_services.sync_user_action_item_push(user=self.user)

        self.assertIsNone(ActionItemPushState.objects.get(tag=self.tag(self.acme, acme_req)).closed_at)
        self.assertEqual(webpush.call_count, 1)
        payload = self.payloads(webpush)[0]
        self.assertEqual(payload["tag"], self.tag(self.beta, beta_req))
        # The service worker must not drop the notification of the company that failed.
        self.assertEqual(payload["active_tags"], sorted([self.tag(self.acme, acme_req), self.tag(self.beta, beta_req)]))
        webpush.reset_mock()

        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        webpush.assert_not_called()

    @patch(WEBPUSH)
    def test_push_failed_on_every_device_is_retried_by_next_sync(self, webpush):
        self.subscribe()
        req = self.pending_request(self.acme)
        webpush.side_effect = WebPushException("Push failed", response=Mock(status_code=500))
        with self.assertLogs("apps.modules.notifications.push_services", level="WARNING"):
            self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        self.assertIsNotNone(ActionItemPushState.objects.get(tag=self.tag(self.acme, req)).closed_at)
        webpush.reset_mock()
        webpush.side_effect = None

        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 1)

        self.assertEqual(webpush.call_count, 1)
        self.assertIsNone(ActionItemPushState.objects.get(tag=self.tag(self.acme, req)).closed_at)

    @patch(WEBPUSH)
    def test_push_delivered_to_one_of_two_devices_is_not_retried(self, webpush):
        self.subscribe(n=1)
        self.subscribe(n=2)
        self.pending_request(self.acme)
        webpush.side_effect = [WebPushException("Push failed", response=Mock(status_code=500)), None]
        push_services.sync_user_action_item_push(user=self.user)
        webpush.reset_mock()
        webpush.side_effect = None

        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        webpush.assert_not_called()

    @patch(WEBPUSH)
    def test_inactive_user_gets_nothing_and_loses_subscriptions(self, webpush):
        subscription = self.subscribe()
        req = self.pending_request(self.acme)
        ActionItemPushState.objects.create(
            tenant=self.acme, user=self.user, tag=self.tag(self.acme, req), sent_at=timezone.now()
        )
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.user.refresh_from_db()

        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        self.assertEqual(push_services.sync_users([self.user.id]), 0)

        webpush.assert_not_called()
        subscription.refresh_from_db()
        self.assertIsNotNone(subscription.revoked_at)
        self.assertEqual(subscription.revoke_reason, PushSubscription.REVOKE_REASON_INACTIVE)
        self.assertIsNotNone(ActionItemPushState.objects.get(tag=self.tag(self.acme, req)).closed_at)

    @patch(WEBPUSH)
    def test_without_devices_open_states_are_closed(self, webpush):
        req = self.pending_request(self.acme)
        ActionItemPushState.objects.create(
            tenant=self.acme, user=self.user, tag=self.tag(self.acme, req), sent_at=timezone.now()
        )

        push_services.sync_user_action_item_push(user=self.user)

        webpush.assert_not_called()
        self.assertIsNotNone(ActionItemPushState.objects.get(tag=self.tag(self.acme, req)).closed_at)

    @patch(WEBPUSH)
    def test_baseline_marks_waiting_items_without_push_then_only_new_items_are_pushed(self, webpush):
        self.subscribe()
        first = self.pending_request(self.acme)
        second = self.pending_request(self.beta)

        self.assertEqual(push_services.record_action_item_baseline(user=self.user), 2)
        webpush.assert_not_called()
        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)
        webpush.assert_not_called()

        third = self.pending_request(self.acme)
        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 1)

        payload = self.payloads(webpush)[0]
        self.assertEqual(payload["tag"], self.tag(self.acme, third))
        self.assertEqual(payload["count"], 3)
        self.assertEqual(
            payload["active_tags"],
            sorted([self.tag(self.acme, first), self.tag(self.beta, second), self.tag(self.acme, third)]),
        )

    @patch(WEBPUSH)
    def test_sync_clears_hook_request_and_records_sync_time(self, webpush):
        subscription = self.subscribe()
        self.assertEqual(push_services.request_sync_for_users([self.user.id, self.next_user.id]), 1)
        subscription.refresh_from_db()
        self.assertIsNotNone(subscription.sync_requested_at)

        push_services.sync_user_action_item_push(user=self.user)

        subscription.refresh_from_db()
        self.assertIsNone(subscription.sync_requested_at)
        self.assertIsNotNone(subscription.synced_at)

    def test_oversized_payload_sends_null_active_tags(self):
        req = self.pending_request(self.acme)
        item = {"title": "t", "amount": Decimal("1"), "currency": "UZS", "link": f"/requests/{req.id}"}
        many_tags = [f"acme-ps:request-{i}" for i in range(500)]

        payload = push_services.build_show_payload(
            tenant=self.acme, item=item, tag=many_tags[0], count=500, active_tags=many_tags
        )

        self.assertIsNone(payload["active_tags"])
        self.assertEqual(payload["count"], 500)

    def test_payload_has_company_title_amount_and_company_link(self):
        item = {"title": "Закупка", "amount": Decimal("1500.50"), "currency": "UZS", "link": "/requests/5"}
        payload = push_services.build_show_payload(
            tenant=self.acme, item=item, tag="acme-ps:request-5", count=3, active_tags=["acme-ps:request-5"]
        )
        self.assertEqual(payload["title"], "Acme: Закупка")
        self.assertEqual(payload["body"], "1 500.50 UZS")
        self.assertEqual(payload["url"], "/app/requests/5?company=acme-ps")
        self.assertEqual(payload["count"], 3)

    def test_payload_whole_amount_has_no_decimals_and_missing_amount_gives_empty_body(self):
        item = {"title": "Закупка", "amount": Decimal("1500000.00"), "currency": "UZS", "link": "/requests/5"}
        payload = push_services.build_show_payload(tenant=self.acme, item=item, tag="t", count=1, active_tags=[])
        self.assertEqual(payload["body"], "1 500 000 UZS")
        item["amount"] = None
        item["currency"] = ""
        payload = push_services.build_show_payload(tenant=self.acme, item=item, tag="t", count=1, active_tags=[])
        self.assertEqual(payload["body"], "")


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", **VAPID)
class SyncUsersForObjectTests(PushFixturesMixin, TestCase):
    def setUp(self):
        self.make_fixtures()

    @patch(WEBPUSH)
    def test_previous_approver_closed_and_next_approver_notified(self, webpush):
        self.subscribe(user=self.user)
        self.subscribe(user=self.next_user)
        req = self.pending_request(self.acme)
        Approval.objects.create(request=req, approver_user=self.next_user, step=2, step_type=Approval.STEP_TYPE_SERIAL)
        push_services.sync_user_action_item_push(user=self.user)
        webpush.reset_mock()
        # Step 1 confirmed: only the open state links the previous approver to the object.
        Approval.objects.filter(request=req, step=1).update(decision=Approval.DECISION_APPROVED)
        Request.all_objects.filter(pk=req.pk).update(status=Request.STATUS_PROGRESS_2)

        push_services.sync_users_for_object(tenant=self.acme, kind="request", object_id=req.id)

        self.assertIsNotNone(ActionItemPushState.objects.get(user=self.user, tag=self.tag(self.acme, req)).closed_at)
        self.assertIsNone(ActionItemPushState.objects.get(user=self.next_user, tag=self.tag(self.acme, req)).closed_at)
        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(webpush.call_args.kwargs["subscription_info"]["endpoint"], "https://fcm.googleapis.com/fcm/send/ps-next-1")

    def test_tag_of_one_company_does_not_select_users_of_another(self):
        req = self.pending_request(self.acme, user=self.next_user)
        ActionItemPushState.objects.create(
            tenant=self.acme, user=self.user, tag=self.tag(self.acme, req), sent_at=timezone.now()
        )

        self.assertEqual(
            push_services.affected_user_ids(tenant=self.beta, kind="request", object_id=req.id), set()
        )
        self.assertEqual(
            push_services.affected_user_ids(tenant=self.acme, kind="request", object_id=req.id),
            {self.user.id, self.next_user.id},
        )

    @patch(WEBPUSH)
    def test_one_failing_user_does_not_stop_others(self, webpush):
        self.subscribe(user=self.next_user)
        req = self.pending_request(self.acme, user=self.next_user)
        Approval.objects.create(request=req, approver_user=self.user, step=1, step_type=Approval.STEP_TYPE_SERIAL)
        real_sync = push_services.sync_user_action_item_push

        def flaky(*, user):
            if user.id == self.user.id:
                raise RuntimeError("boom")
            return real_sync(user=user)

        with patch.object(push_services, "sync_user_action_item_push", side_effect=flaky), self.assertLogs(
            "apps.modules.notifications.push_services", level="ERROR"
        ) as logs:
            push_services.sync_users_for_object(tenant=self.acme, kind="request", object_id=req.id)

        self.assertEqual(webpush.call_count, 1)
        self.assertTrue(any(f"user_id={self.user.id}" in line for line in logs.output))


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", **VAPID)
class SendWebPushTests(PushFixturesMixin, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.subscription = self.subscribe()

    def _error(self, status_code):
        return WebPushException("Push failed", response=Mock(status_code=status_code))

    @patch(WEBPUSH)
    def test_410_revokes_subscription_and_logs_info(self, webpush):  # p.22
        webpush.side_effect = self._error(410)

        with self.assertLogs("apps.modules.notifications.push_services", level="INFO") as logs:
            ok = push_services.send_web_push(self.subscription, {"type": "show"})

        self.assertFalse(ok)
        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.revoked_at)
        self.assertEqual(self.subscription.revoke_reason, PushSubscription.REVOKE_REASON_GONE)
        self.assertTrue(any(line.startswith("INFO:") and "gone" in line for line in logs.output))

    @patch(WEBPUSH)
    def test_404_revokes_subscription(self, webpush):
        webpush.side_effect = self._error(404)

        push_services.send_web_push(self.subscription, {"type": "show"})

        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.revoked_at)

    @patch(WEBPUSH)
    def test_500_keeps_subscription_and_logs_error_without_secrets(self, webpush):  # p.22
        webpush.side_effect = self._error(500)

        with self.assertLogs("apps.modules.notifications.push_services", level="ERROR") as logs:
            ok = push_services.send_web_push(self.subscription, {"type": "show"})

        self.assertFalse(ok)
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.revoked_at)
        self.assertIsNone(self.subscription.last_success_at)
        text = "\n".join(logs.output)
        self.assertIn(f"subscription_id={self.subscription.id}", text)
        for secret in (self.subscription.endpoint, "p256dh-secret-1", "auth-secret-1", "test-private-key"):
            self.assertNotIn(secret, text)

    @patch(WEBPUSH)
    def test_network_error_text_with_endpoint_is_not_logged(self, webpush):
        webpush.side_effect = ConnectionError(f"Max retries exceeded with url: {self.subscription.endpoint}")

        with self.assertLogs("apps.modules.notifications.push_services", level="ERROR") as logs:
            self.assertFalse(push_services.send_web_push(self.subscription, {"type": "show"}))

        self.assertNotIn(self.subscription.endpoint, "\n".join(logs.output))
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.revoked_at)

    @patch(WEBPUSH)
    def test_endpoint_outside_allow_list_is_revoked_without_request(self, webpush):
        for n, endpoint in enumerate(("https://10.0.0.5/push", "https://backend_v2:8000/api/x"), start=10):
            subscription = PushSubscription.objects.create(
                user=self.user, endpoint=endpoint, endpoint_hash=push_services.endpoint_hash(endpoint), p256dh="k", auth="a"
            )
            with self.subTest(endpoint=endpoint), self.assertLogs(
                "apps.modules.notifications.push_services", level="WARNING"
            ) as logs:
                self.assertFalse(push_services.send_web_push(subscription, {"type": "show"}))
            subscription.refresh_from_db()
            self.assertEqual(subscription.revoke_reason, PushSubscription.REVOKE_REASON_NOT_ALLOWED)
            self.assertNotIn(endpoint, "\n".join(logs.output))
        webpush.assert_not_called()

    def test_push_session_never_follows_redirects(self):
        with patch("requests.Session.request", return_value=Mock(status_code=201)) as parent:
            push_services._NoRedirectSession().post("https://fcm.googleapis.com/fcm/send/x", data=b"")

        self.assertIs(parent.call_args.kwargs["allow_redirects"], False)

    def test_endpoint_allow_list(self):
        allowed = (
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://web.push.apple.com/QH-abc",
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "https://wns2-par02p.notify.windows.com/w/?token=abc",
            "https://fcm.googleapis.com:443/fcm/send/abc",
        )
        refused = (
            "http://fcm.googleapis.com/fcm/send/abc",
            "https://fcm.googleapis.com:8443/fcm/send/abc",
            "https://user:pass@fcm.googleapis.com/fcm/send/abc",
            "https://fcm.googleapis.com.evil.example/x",
            "https://evilpush.apple.com/x",
            "https://push.apple.com/x",
            "https://127.0.0.1/x",
            "https://[::1]/x",
            "https://localhost/x",
            "https://backend_v2/x",
            "https://push.example.net/send/x",
            "https://evil.example\\@fcm.googleapis.com/x",
            "",
        )
        for endpoint in allowed:
            with self.subTest(endpoint=endpoint):
                self.assertTrue(push_services.endpoint_allowed(endpoint))
        for endpoint in refused:
            with self.subTest(endpoint=endpoint):
                self.assertFalse(push_services.endpoint_allowed(endpoint))

    @patch(WEBPUSH)
    def test_gone_device_is_skipped_for_next_items_in_same_sync(self, webpush):
        webpush.side_effect = self._error(410)
        self.pending_request(self.acme)
        self.pending_request(self.acme)

        push_services.sync_user_action_item_push(user=self.user)

        self.assertEqual(webpush.call_count, 1)
