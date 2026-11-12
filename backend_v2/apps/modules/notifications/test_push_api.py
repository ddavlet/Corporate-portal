"""Web Push subscription API: /api/notifications/push/* (shared portal host, no company)."""

import logging
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.notifications import push_services
from apps.modules.notifications.models import ActionItemPushState, PushSubscription
from apps.modules.notifications.push_services import endpoint_hash
from apps.modules.requests.models import Approval, Request
from apps.tenants import shared_host as sh
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()

SHARED = "app.example.com"
VAPID = {"VAPID_PUBLIC_KEY": "test-public-key", "VAPID_PRIVATE_KEY": "test-private-key", "VAPID_SUBJECT": "mailto:t@example.com"}
NO_VAPID = {"VAPID_PUBLIC_KEY": "", "VAPID_PRIVATE_KEY": "", "VAPID_SUBJECT": ""}
ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-token-1"
WEBPUSH = "apps.modules.notifications.push_services.webpush"
SUBSCRIBE_URL = "/api/notifications/push/subscribe/"
UNSUBSCRIBE_URL = "/api/notifications/push/unsubscribe/"
KEY_URL = "/api/notifications/push/vapid-public-key/"


@override_settings(BASE_DOMAIN="example.com", PORTAL_SHARED_HOST=SHARED, ALLOWED_HOSTS=["*"], **VAPID)
class PushSubscriptionApiTests(APITestCase):
    def setUp(self):
        self.acme = Tenant.objects.create(name="Acme", subdomain="acme-push", is_active=True)
        self.user = User.objects.create_user(username="push-user", password="x")
        self.other = User.objects.create_user(username="push-other", password="x")
        self.outsider = User.objects.create_user(username="push-outsider", password="x")
        TenantMembership.objects.create(tenant=self.acme, user=self.user, is_active=True)
        TenantMembership.objects.create(tenant=self.acme, user=self.other, is_active=True)

    # Real JWT through the full stack: force_authenticate would skip the shared-host auth class.
    def _post(self, url, data, *, user=None, host=SHARED, anonymous=False, tenant_header=None):
        headers = {"HTTP_HOST": host, "HTTP_USER_AGENT": "TestBrowser/1.0"}
        if not anonymous:
            token = RefreshToken.for_user(user or self.user).access_token
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        if tenant_header:
            headers["HTTP_X_TENANT"] = tenant_header
        return self.client.post(url, data, format="json", **headers)

    def _get(self, url, *, user=None, anonymous=False):
        headers = {"HTTP_HOST": SHARED}
        if not anonymous:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {RefreshToken.for_user(user or self.user).access_token}"
        return self.client.get(url, **headers)

    def _payload(self, endpoint=ENDPOINT, p256dh="p256dh-key-1", auth="auth-secret-1"):
        return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}

    # --- paths ----------------------------------------------------------------------

    def test_push_paths_need_no_company_on_shared_host(self):
        for path in (SUBSCRIBE_URL, UNSUBSCRIBE_URL, KEY_URL):
            with self.subTest(path=path):
                self.assertTrue(sh.is_tenantless_path(path))

    # --- vapid-public-key -----------------------------------------------------------

    def test_vapid_public_key(self):
        res = self._get(KEY_URL)

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json(), {"enabled": True, "public_key": "test-public-key"})

    @override_settings(**NO_VAPID)
    def test_vapid_public_key_without_vapid(self):  # p.23
        res = self._get(KEY_URL)

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json(), {"enabled": False, "public_key": None})

    def test_vapid_public_key_anonymous_gets_401(self):
        self.assertEqual(self._get(KEY_URL, anonymous=True).status_code, 401)

    # --- subscribe ------------------------------------------------------------------

    def test_subscribe_creates_then_updates_without_duplicate(self):  # p.19
        first = self._post(SUBSCRIBE_URL, self._payload())
        second = self._post(SUBSCRIBE_URL, self._payload(p256dh="p256dh-key-2", auth="auth-secret-2"))

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(PushSubscription.objects.count(), 1)
        sub = PushSubscription.objects.get()
        self.assertEqual(sub.user_id, self.user.id)
        self.assertEqual(sub.endpoint, ENDPOINT)
        self.assertEqual(sub.endpoint_hash, endpoint_hash(ENDPOINT))
        self.assertEqual((sub.p256dh, sub.auth), ("p256dh-key-2", "auth-secret-2"))
        self.assertEqual(sub.user_agent, "TestBrowser/1.0")
        self.assertIsNone(sub.revoked_at)

    def test_subscribe_ignores_company_header(self):
        res = self._post(SUBSCRIBE_URL, self._payload(), tenant_header="unknown-company")

        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(PushSubscription.objects.get().user_id, self.user.id)

    def test_subscribe_after_revoke_reactivates(self):
        self._post(SUBSCRIBE_URL, self._payload())
        self.assertEqual(self._post(UNSUBSCRIBE_URL, {"endpoint": ENDPOINT}).status_code, 204)

        res = self._post(SUBSCRIBE_URL, self._payload())

        self.assertEqual(res.status_code, 200, res.content)
        sub = PushSubscription.objects.get()
        self.assertIsNone(sub.revoked_at)
        self.assertEqual(sub.revoke_reason, "")

    def test_subscribe_rebinds_endpoint_to_current_user(self):
        self._post(SUBSCRIBE_URL, self._payload())

        res = self._post(SUBSCRIBE_URL, self._payload(), user=self.other)

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(PushSubscription.objects.get().user_id, self.other.id)

    def test_subscribe_on_tenant_subdomain_gets_409(self):
        res = self._post(SUBSCRIBE_URL, self._payload(), host="acme-push.example.com")

        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.json()["code"], "shared_host_only")
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(**NO_VAPID)
    def test_subscribe_without_vapid_gets_409(self):  # p.23
        res = self._post(SUBSCRIBE_URL, self._payload())

        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.json()["code"], "push_disabled")
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscribe_http_endpoint_gets_400(self):
        res = self._post(SUBSCRIBE_URL, self._payload(endpoint="http://fcm.googleapis.com/fcm/send/x"))

        self.assertEqual(res.status_code, 400, res.content)
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscribe_endpoint_outside_push_services_gets_400(self):
        for endpoint in (
            "https://10.0.0.5/push",
            "https://127.0.0.1/push",
            "https://localhost/push",
            "https://backend_v2:8000/api/admin/",
            "https://fcm.googleapis.com:8443/fcm/send/x",
            "https://user:pw@fcm.googleapis.com/fcm/send/x",
            "https://push.example.net/send/x",
        ):
            with self.subTest(endpoint=endpoint):
                res = self._post(SUBSCRIBE_URL, self._payload(endpoint=endpoint))
                self.assertEqual(res.status_code, 400, res.content)
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscribe_accepts_known_push_services(self):
        for n, endpoint in enumerate(
            (
                "https://web.push.apple.com/QH-token",
                "https://updates.push.services.mozilla.com/wpush/v2/token",
                "https://wns2-par02p.notify.windows.com/w/?token=abc",
            )
        ):
            with self.subTest(endpoint=endpoint):
                res = self._post(SUBSCRIBE_URL, self._payload(endpoint=endpoint, p256dh=f"k{n}", auth=f"a{n}"))
                self.assertEqual(res.status_code, 201, res.content)

    def test_subscribe_keeps_at_most_ten_active_devices_per_user(self):
        for n in range(push_services.MAX_ACTIVE_SUBSCRIPTIONS_PER_USER + 1):
            res = self._post(SUBSCRIBE_URL, self._payload(endpoint=f"{ENDPOINT}-{n}"))
            self.assertEqual(res.status_code, 201, res.content)

        active = PushSubscription.objects.filter(user=self.user, revoked_at__isnull=True)
        self.assertEqual(active.count(), push_services.MAX_ACTIVE_SUBSCRIPTIONS_PER_USER)
        oldest = PushSubscription.objects.get(endpoint=f"{ENDPOINT}-0")
        self.assertIsNotNone(oldest.revoked_at)
        self.assertEqual(oldest.revoke_reason, PushSubscription.REVOKE_REASON_LIMIT)

    def test_subscribe_active_foreign_endpoint_with_other_keys_gets_409(self):
        self._post(SUBSCRIBE_URL, self._payload())

        res = self._post(SUBSCRIBE_URL, self._payload(p256dh="forged", auth="forged"), user=self.other)

        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.json()["code"], "endpoint_taken")
        sub = PushSubscription.objects.get()
        self.assertEqual((sub.user_id, sub.p256dh), (self.user.id, "p256dh-key-1"))

    def test_subscribe_revoked_foreign_endpoint_is_taken_over(self):
        self._post(SUBSCRIBE_URL, self._payload())
        self._post(UNSUBSCRIBE_URL, {"endpoint": ENDPOINT})

        res = self._post(SUBSCRIBE_URL, self._payload(p256dh="new-key", auth="new-auth"), user=self.other)

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(PushSubscription.objects.get().user_id, self.other.id)

    @override_settings(N8N_INTEGRATION_TOKEN="")
    @patch(WEBPUSH)
    def test_first_device_gets_no_push_for_items_already_waiting(self, webpush):
        waiting = [self._pending_request() for _ in range(3)]

        self.assertEqual(self._post(SUBSCRIBE_URL, self._payload()).status_code, 201)
        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 0)

        webpush.assert_not_called()
        self.assertEqual(
            ActionItemPushState.objects.filter(user=self.user, closed_at__isnull=True).count(), len(waiting)
        )
        self._pending_request()
        self.assertEqual(push_services.sync_user_action_item_push(user=self.user), 1)
        self.assertEqual(webpush.call_count, 1)

    def _pending_request(self):
        req = Request.all_objects.create(
            tenant=self.acme,
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

    def test_subscribe_without_keys_gets_400(self):
        res = self._post(SUBSCRIBE_URL, {"endpoint": ENDPOINT})

        self.assertEqual(res.status_code, 400, res.content)

    def test_subscribe_anonymous_gets_401(self):
        self.assertEqual(self._post(SUBSCRIBE_URL, self._payload(), anonymous=True).status_code, 401)

    def test_subscribe_without_any_company_gets_403(self):
        res = self._post(SUBSCRIBE_URL, self._payload(), user=self.outsider)

        self.assertEqual(res.status_code, 403, res.content)
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscribe_with_only_inactive_membership_gets_403(self):
        TenantMembership.objects.filter(user=self.user).update(is_active=False)

        self.assertEqual(self._post(SUBSCRIBE_URL, self._payload()).status_code, 403)

    # --- unsubscribe ----------------------------------------------------------------

    def test_unsubscribe_revokes_and_keeps_row(self):  # p.24
        self._post(SUBSCRIBE_URL, self._payload())

        res = self._post(UNSUBSCRIBE_URL, {"endpoint": ENDPOINT})

        self.assertEqual(res.status_code, 204, res.content)
        sub = PushSubscription.objects.get()
        self.assertIsNotNone(sub.revoked_at)
        self.assertEqual(sub.revoke_reason, PushSubscription.REVOKE_REASON_USER)

    def test_unsubscribe_foreign_endpoint_gets_404(self):
        self._post(SUBSCRIBE_URL, self._payload())

        res = self._post(UNSUBSCRIBE_URL, {"endpoint": ENDPOINT}, user=self.other)

        self.assertEqual(res.status_code, 404, res.content)
        self.assertEqual(res.json()["code"], "not_found")
        self.assertIsNone(PushSubscription.objects.get().revoked_at)

    def test_unsubscribe_unknown_endpoint_gets_404(self):
        res = self._post(UNSUBSCRIBE_URL, {"endpoint": "https://push.example.net/unknown"})

        self.assertEqual(res.status_code, 404, res.content)

    def test_unsubscribe_anonymous_gets_401(self):
        self.assertEqual(self._post(UNSUBSCRIBE_URL, {"endpoint": ENDPOINT}, anonymous=True).status_code, 401)

    def test_endpoint_and_keys_are_not_logged(self):
        with self.assertLogs("apps", level="DEBUG") as logs:
            # One harmless record so assertLogs does not fail when nothing else is logged.
            logging.getLogger("apps.test").debug("marker")
            self._post(SUBSCRIBE_URL, self._payload())
            self._post(UNSUBSCRIBE_URL, {"endpoint": ENDPOINT})
        text = "\n".join(logs.output)
        for secret in (ENDPOINT, "p256dh-key-1", "auth-secret-1"):
            self.assertNotIn(secret, text)
