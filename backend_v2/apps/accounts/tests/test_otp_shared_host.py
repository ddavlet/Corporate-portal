"""OTP on the shared portal host: no company in the request, the bot of the user's first OTP company."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import OtpChallenge
from apps.accounts.views_otp import (
    OTP_DIGITS,
    OTP_MAX_ATTEMPTS,
    OTP_REQUEST_MAX_IN_WINDOW,
    _check_code,
    _hash_code,
    _public_ok_message,
    _verify_challenge_response,
)
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()

SHARED = "app.example.com"
REQUEST_URL = "/api/auth/otp/request/"
VERIFY_URL = "/api/auth/otp/verify/"


@override_settings(BASE_DOMAIN="example.com", PORTAL_SHARED_HOST=SHARED, ALLOWED_HOSTS=["*"])
class SharedHostOtpTests(APITestCase):
    def setUp(self):
        cache.clear()
        # "Alpha" sorts first but has OTP off; "Beta" is the expected sender.
        self.alpha = Tenant.objects.create(name="Alpha", subdomain="alpha", is_active=True, telegram_otp_enabled=False)
        self.beta = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True, telegram_otp_enabled=True)
        self.gamma = Tenant.objects.create(name="Gamma", subdomain="gamma", is_active=True, telegram_otp_enabled=True)
        for tenant, token in ((self.alpha, "1:ALPHA"), (self.beta, "2:BETA"), (self.gamma, "3:GAMMA")):
            tenant.set_telegram_bot_token(token)
            tenant.save(update_fields=["telegram_bot_token_enc"])

        self.user = User.objects.create_user(username="shared_otp", password="x")
        self.user.telegram_chat_id = 555001
        self.user.save(update_fields=["telegram_chat_id"])
        for tenant in (self.alpha, self.beta, self.gamma):
            TenantMembership.objects.create(tenant=tenant, user=self.user, is_active=True)

    def _post(self, url, data, host=SHARED):
        return self.client.post(url, data, format="json", HTTP_HOST=host)

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_code_is_sent_by_first_company_with_otp_and_bot(self, gw_mock):
        gw_mock.return_value = {"ok": True}

        res = self._post(REQUEST_URL, {"username": "shared_otp"})

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.json(), _public_ok_message())
        gw_mock.assert_called_once()
        self.assertEqual(gw_mock.call_args.kwargs["tenant"], self.beta)
        payload = gw_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["bot_token"], "2:BETA")
        self.assertEqual(payload["recipient_id"], "555001")
        self.assertEqual(OtpChallenge.objects.get(user=self.user).tenant, self.beta)

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_unknown_user_and_user_without_company_look_the_same(self, gw_mock):
        TenantMembership.objects.filter(user=self.user, tenant__in=[self.beta, self.gamma]).update(is_active=False)

        unknown = self._post(REQUEST_URL, {"username": "nobody_here"})
        no_company = self._post(REQUEST_URL, {"username": "shared_otp"})

        self.assertEqual(unknown.status_code, status.HTTP_200_OK)
        self.assertEqual(no_company.status_code, status.HTTP_200_OK)
        self.assertEqual(unknown.json(), no_company.json())
        gw_mock.assert_not_called()
        self.assertFalse(OtpChallenge.objects.exists())

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_inactive_company_is_skipped(self, gw_mock):
        gw_mock.return_value = {"ok": True}
        Tenant.objects.filter(pk=self.beta.pk).update(is_active=False)

        self._post(REQUEST_URL, {"username": "shared_otp"})

        self.assertEqual(gw_mock.call_args.kwargs["tenant"], self.gamma)

    def test_gateway_failure_answers_like_success(self):
        cases = (
            {"side_effect": RuntimeError("gateway down")},
            {"return_value": None},
            {"return_value": {"ok": False, "description": "chat not found"}},
        )
        for case in cases:
            with self.subTest(case=case):
                cache.clear()
                with patch("apps.accounts.views_otp.post_messaging_gateway", **case), self.assertLogs(
                    "apps.accounts.views_otp", level="ERROR"
                ) as logs:
                    res = self._post(REQUEST_URL, {"username": "shared_otp"})
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                self.assertEqual(res.json(), _public_ok_message())
                self.assertTrue(any("shared-host OTP send failed" in line for line in logs.output))
                self.assertFalse(any("2:BETA" in line for line in logs.output))

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_repeat_request_is_rate_limited_for_any_username(self, gw_mock):
        gw_mock.return_value = {"ok": True}
        for username in ("shared_otp", "nobody_here"):
            with self.subTest(username=username):
                self.assertEqual(self._post(REQUEST_URL, {"username": username}).status_code, 200)
                self.assertEqual(
                    self._post(REQUEST_URL, {"username": username}).status_code,
                    status.HTTP_429_TOO_MANY_REQUESTS,
                )

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_next_company_is_tried_when_first_bot_fails(self, gw_mock):
        gw_mock.side_effect = [None, {"ok": True}]

        with self.assertLogs("apps.accounts.views_otp", level="ERROR") as logs:
            res = self._post(REQUEST_URL, {"username": "shared_otp"})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json(), _public_ok_message())
        self.assertEqual([c.kwargs["tenant"] for c in gw_mock.call_args_list], [self.beta, self.gamma])
        self.assertEqual(gw_mock.call_args_list[1].kwargs["payload"]["bot_token"], "3:GAMMA")
        self.assertTrue(any(f"tenant_id={self.beta.id}" in line for line in logs.output))
        # One challenge per request, owned by the company whose bot delivered the code.
        self.assertEqual(OtpChallenge.objects.get(user=self.user).tenant, self.gamma)

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_exhausted_window_answers_like_unknown_user(self, gw_mock):
        gw_mock.return_value = {"ok": True}
        for _ in range(OTP_REQUEST_MAX_IN_WINDOW):
            self._challenge(self.beta)

        known = self._post(REQUEST_URL, {"username": "shared_otp"})
        unknown = self._post(REQUEST_URL, {"username": "nobody_here"})

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.status_code, status.HTTP_200_OK)
        self.assertEqual(known.json(), unknown.json())
        gw_mock.assert_not_called()
        self.assertEqual(OtpChallenge.objects.count(), OTP_REQUEST_MAX_IN_WINDOW)

    def test_code_comes_from_csprng_with_otp_digits(self):
        for host in (SHARED, "gamma.example.com"):
            with self.subTest(host=host):
                cache.clear()
                OtpChallenge.objects.all().delete()
                with patch("apps.accounts.views_otp.secrets.randbelow", return_value=42) as rand_mock, patch(
                    "apps.accounts.views_otp.post_messaging_gateway", return_value={"ok": True}
                ) as gw_mock:
                    res = self._post(REQUEST_URL, {"username": "shared_otp"}, host=host)

                self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
                rand_mock.assert_called_once_with(10**OTP_DIGITS)
                code = "42".zfill(OTP_DIGITS)
                self.assertIn(f"<code>{code}</code>", gw_mock.call_args.kwargs["payload"]["text"])
                self.assertTrue(_check_code(code, OtpChallenge.objects.get(user=self.user).code_hash))

    def test_verify_stale_challenge_cannot_exceed_attempts(self):
        stale = self._challenge(self.beta)
        OtpChallenge.objects.filter(pk=stale.pk).update(attempts=OTP_MAX_ATTEMPTS)

        res = _verify_challenge_response(user=self.user, challenge=stale, code="123456")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access", res.data)
        stale.refresh_from_db()
        self.assertEqual(stale.attempts, OTP_MAX_ATTEMPTS)
        self.assertIsNone(stale.consumed_at)

    def test_verify_stale_challenge_cannot_be_consumed_twice(self):
        stale = self._challenge(self.beta)
        OtpChallenge.objects.filter(pk=stale.pk).update(consumed_at=timezone.now())

        res = _verify_challenge_response(user=self.user, challenge=stale, code="123456")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access", res.data)

    def _challenge(self, tenant, code="123456"):
        return OtpChallenge.objects.create(
            user=self.user,
            tenant=tenant,
            code_hash=_hash_code(code),
            expires_at=timezone.now() + timedelta(minutes=5),
        )

    def test_verify_issues_tokens(self):
        challenge = self._challenge(self.beta)

        res = self._post(VERIFY_URL, {"username": "shared_otp", "code": "123456"})

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertIn("access", res.json())
        self.assertIn("refresh", res.json())
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)

    def test_verify_wrong_code_counts_attempt(self):
        challenge = self._challenge(self.beta)

        res = self._post(VERIFY_URL, {"username": "shared_otp", "code": "000000"})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json(), {"detail": "Неверный код."})
        challenge.refresh_from_db()
        self.assertEqual(challenge.attempts, 1)

    def test_verify_rejects_inactive_company_or_membership(self):
        for setup in ("tenant", "membership"):
            with self.subTest(setup=setup):
                OtpChallenge.objects.all().delete()
                self._challenge(self.beta)
                if setup == "tenant":
                    Tenant.objects.filter(pk=self.beta.pk).update(is_active=False)
                else:
                    TenantMembership.objects.filter(tenant=self.beta, user=self.user).update(is_active=False)

                res = self._post(VERIFY_URL, {"username": "shared_otp", "code": "123456"})

                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                Tenant.objects.filter(pk=self.beta.pk).update(is_active=True)
                TenantMembership.objects.filter(tenant=self.beta, user=self.user).update(is_active=True)

    @patch("apps.accounts.views_otp.post_messaging_gateway")
    def test_subdomain_keeps_tenant_otp(self, gw_mock):
        gw_mock.return_value = None

        res = self._post(REQUEST_URL, {"username": "shared_otp"}, host="gamma.example.com")

        # Unchanged subdomain behavior: the tenant's own bot, 503 on gateway failure.
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(gw_mock.call_args_list[0].kwargs["tenant"], self.gamma)

    def test_subdomain_verify_only_counts_own_tenant(self):
        self._challenge(self.beta)

        res = self._post(VERIFY_URL, {"username": "shared_otp", "code": "123456"}, host="gamma.example.com")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
