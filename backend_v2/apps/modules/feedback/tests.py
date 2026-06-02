from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.feedback.models import PortalFeedback
from apps.modules.feedback.services import feedback_ai_webhook_url, post_feedback_ai_refine
from apps.tenants.models import Tenant, TenantIntegrationConfig, TenantMembership, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="kolberg.uz", N8N_FEEDBACK_AI_WEBHOOK_PATH="n8n/ai/dispatch")
class FeedbackWebhookUrlTests(TestCase):
    def test_public_https_tenant_url(self):
        self.assertEqual(
            feedback_ai_webhook_url(tenant_subdomain="lemonfit"),
            "https://lemonfit.kolberg.uz/n8n/ai/dispatch/",
        )

    @override_settings(BASE_DOMAIN="example.com", N8N_FEEDBACK_AI_WEBHOOK_PATH="n8n/ai/dispatch")
    def test_public_https_other_tenant(self):
        self.assertEqual(
            feedback_ai_webhook_url(tenant_subdomain="acme"),
            "https://acme.example.com/n8n/ai/dispatch/",
        )


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class FeedbackApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u1", password="x", full_name="User One")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER)

    def _auth(self):
        token = str(RefreshToken.for_user(self.user).access_token)
        return {"HTTP_HOST": "acme.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    @patch("apps.modules.feedback.views.post_feedback_ai_refine")
    def test_ai_refine_returns_feedback(self, mocked_refine):
        mocked_refine.return_value = "Refined text."
        res = self.client.post(
            "/api/feedback/ai-refine/",
            {"kind": "error", "text": "broken"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data["feedback"], "Refined text.")
        mocked_refine.assert_called_once()
        call_kw = mocked_refine.call_args.kwargs
        self.assertEqual(call_kw["tenant"].pk, self.tenant.pk)
        self.assertEqual(
            call_kw["body"],
            {"action": "feedback_former", "payload": {"kind": "error", "text": "broken"}},
        )

    @patch("apps.modules.feedback.views.TelegramDispatcher.send")
    def test_submit_saves_and_dispatches_when_chat_configured(self, mocked_send):
        from apps.modules.telegram_approvals.models import TelegramMessage
        tm = TelegramMessage(
            tenant=self.tenant,
            recipient_id="42424242",
            message_id=12345,
            sent_at=timezone.now(),
        )
        mocked_send.return_value = tm
        from apps.tenants.models import TenantIntegrationConfig

        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        cfg.messaging_gateway_feedback_recipient_id = 42424242
        cfg.messaging_gateway_feedback_action = "send_portal_feedback"
        cfg.save()

        res = self.client.post(
            "/api/feedback/submissions/",
            {"kind": "improvement", "body": "Лимит 1000000 сум", "page_path": "/requests"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        fb = PortalFeedback.objects.get()
        self.assertEqual(fb.body, "Лимит 1000000 сум")
        self.assertEqual(fb.delivery_status, PortalFeedback.DELIVERY_SENT)
        mocked_send.assert_called_once()
        call_kw = mocked_send.call_args.kwargs
        self.assertEqual(call_kw["action"], "send_portal_feedback")
        self.assertEqual(call_kw["recipient_id"], 42424242)

    @patch("apps.modules.feedback.views.TelegramDispatcher.send")
    def test_submit_skips_telegram_without_chat(self, mocked_send):
        res = self.client.post(
            "/api/feedback/submissions/",
            {"kind": "error", "body": "Bug"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.data["delivery"]["status"], "skipped")
        mocked_send.assert_not_called()
        fb = PortalFeedback.objects.get()
        self.assertEqual(fb.delivery_status, PortalFeedback.DELIVERY_SKIPPED)


@override_settings(
    BASE_DOMAIN="example.com",
    N8N_FEEDBACK_AI_WEBHOOK_PATH="n8n/ai/dispatch",
    N8N_INTEGRATION_TOKEN="",
    ALLOWED_HOSTS=["*"],
)
class FeedbackAiRefineTokenTests(APITestCase):
    """
    Regression tests for the missing X-N8N-Integration-Token header bug.

    Root cause: commit 538f468 refactored messaging integration and accidentally
    removed _bridge_headers() from post_feedback_ai_refine(), so Django stopped
    sending the auth token to n8n. n8n responded with 403, which Django surfaced
    as a 502 with "HTTP 403" in the detail — the user saw 403 in the error modal.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = get_user_model().objects.create_user(username="u1", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER)

    def _auth(self):
        token = str(RefreshToken.for_user(self.user).access_token)
        return {"HTTP_HOST": "acme.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _make_mock_response(self, status_code=200, json_data=None):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or {"feedback": "Refined."}
        if status_code >= 400:
            from requests import HTTPError
            mock_resp.raise_for_status.side_effect = HTTPError(response=mock_resp)
        else:
            mock_resp.raise_for_status.return_value = None
        mock_resp.text = str(json_data)
        return mock_resp

    @patch("apps.modules.feedback.services.requests.post")
    def test_sends_integration_token_from_env(self, mock_post):
        """Token from N8N_INTEGRATION_TOKEN env var is sent as X-N8N-Integration-Token header."""
        mock_post.return_value = self._make_mock_response(json_data={"feedback": "Refined."})
        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        # No per-tenant token — falls back to env setting.
        with self.settings(N8N_INTEGRATION_TOKEN="env-secret-token"):
            post_feedback_ai_refine(
                tenant=self.tenant,
                body={"action": "feedback_former", "payload": {"kind": "error", "text": "bug"}},
            )
        headers_sent = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers_sent.get("X-N8N-Integration-Token"), "env-secret-token")

    @patch("apps.modules.feedback.services.requests.post")
    def test_sends_integration_token_from_tenant_config(self, mock_post):
        """Per-tenant token takes priority over env var."""
        mock_post.return_value = self._make_mock_response(json_data={"feedback": "Refined."})
        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        cfg.set_n8n_integration_token("per-tenant-secret")
        cfg.save()
        with self.settings(N8N_INTEGRATION_TOKEN="env-secret-token"):
            post_feedback_ai_refine(
                tenant=self.tenant,
                body={"action": "feedback_former", "payload": {"kind": "error", "text": "bug"}},
            )
        headers_sent = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers_sent.get("X-N8N-Integration-Token"), "per-tenant-secret")

    @patch("apps.modules.feedback.services.requests.post")
    def test_no_token_header_when_token_not_configured(self, mock_post):
        """When no token is set, header is omitted entirely (not sent as empty string)."""
        mock_post.return_value = self._make_mock_response(json_data={"feedback": "Refined."})
        TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        with self.settings(N8N_INTEGRATION_TOKEN=""):
            post_feedback_ai_refine(
                tenant=self.tenant,
                body={"action": "feedback_former", "payload": {"kind": "error", "text": "bug"}},
            )
        headers_sent = mock_post.call_args.kwargs["headers"]
        self.assertNotIn("X-N8N-Integration-Token", headers_sent)

    @patch("apps.modules.feedback.services.requests.post")
    def test_n8n_403_surfaces_as_502_not_403(self, mock_post):
        """
        Regression: when n8n returns 403 (e.g. missing/wrong token), the view must
        return 502, not pass 403 through to the client. The detail must mention 403
        so operators can diagnose.
        """
        mock_post.return_value = self._make_mock_response(status_code=403)
        res = self.client.post(
            "/api/feedback/ai-refine/",
            {"kind": "error", "text": "bug report"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY, res.content)
        self.assertIn("403", res.data.get("detail", ""))

    @patch("apps.modules.feedback.services.requests.post")
    def test_n8n_200_with_token_returns_feedback(self, mock_post):
        """Happy path: token is sent, n8n returns 200 with feedback field."""
        mock_post.return_value = self._make_mock_response(json_data={"feedback": "Structured text."})
        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        cfg.set_n8n_integration_token("valid-token")
        cfg.save()
        res = self.client.post(
            "/api/feedback/ai-refine/",
            {"kind": "improvement", "text": "make it faster"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data["feedback"], "Structured text.")
        headers_sent = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers_sent.get("X-N8N-Integration-Token"), "valid-token")
