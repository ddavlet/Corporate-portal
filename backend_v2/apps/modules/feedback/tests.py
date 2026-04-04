from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.feedback.models import PortalFeedback
from apps.modules.feedback.services import feedback_ai_webhook_url
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

User = get_user_model()


@override_settings(N8N_INTERNAL_BASE_URL="http://n8n:5678", N8N_FEEDBACK_AI_WEBHOOK_PATH="ai")
class FeedbackWebhookUrlTests(TestCase):
    def test_internal_url_matches_n8n_webhook_path(self):
        self.assertEqual(
            feedback_ai_webhook_url(tenant_subdomain="lemonfit"),
            "http://n8n:5678/webhook/lemonfit/ai",
        )

    @override_settings(N8N_INTERNAL_BASE_URL="", BASE_DOMAIN="example.com", N8N_FEEDBACK_AI_WEBHOOK_PATH="x")
    def test_public_https_when_internal_unset(self):
        self.assertEqual(
            feedback_ai_webhook_url(tenant_subdomain="acme"),
            "https://acme.example.com/x",
        )


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class FeedbackApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u1", password="x", full_name="User One")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER, step=1
        )

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
        self.assertEqual(call_kw["tenant_subdomain"], "acme")
        self.assertEqual(
            call_kw["body"],
            {"type": "feedback_former", "payload": {"kind": "error", "text": "broken"}},
        )

    @patch("apps.modules.feedback.views.post_telegram_bridge")
    def test_submit_saves_and_dispatches_when_chat_configured(self, mocked_bridge):
        mocked_bridge.return_value = {"ok": True}
        from apps.tenants.models import TenantIntegrationConfig

        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        cfg.portal_feedback_telegram_chat_id = 42424242
        cfg.portal_feedback_telegram_action = "send_portal_feedback"
        cfg.save()

        res = self.client.post(
            "/api/feedback/submissions/",
            {"kind": "improvement", "body": "More filters", "page_path": "/requests"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        fb = PortalFeedback.objects.get()
        self.assertEqual(fb.body, "More filters")
        self.assertEqual(fb.delivery_status, PortalFeedback.DELIVERY_SENT)
        mocked_bridge.assert_called_once()
        payload = mocked_bridge.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "send_portal_feedback")
        self.assertEqual(payload["chat_id"], 42424242)
        self.assertEqual(payload["notification_kind"], "portal_feedback")
        self.assertEqual(payload["feedback_id"], fb.id)

    @patch("apps.modules.feedback.views.post_telegram_bridge")
    def test_submit_skips_telegram_without_chat(self, mocked_bridge):
        res = self.client.post(
            "/api/feedback/submissions/",
            {"kind": "error", "body": "Bug"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.data["delivery"]["status"], "skipped")
        mocked_bridge.assert_not_called()
        fb = PortalFeedback.objects.get()
        self.assertEqual(fb.delivery_status, PortalFeedback.DELIVERY_SKIPPED)
