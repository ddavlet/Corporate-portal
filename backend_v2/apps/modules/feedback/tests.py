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

    @patch("apps.modules.feedback.views.post_messaging_gateway")
    def test_submit_saves_and_dispatches_when_chat_configured(self, mocked_gateway):
        mocked_gateway.return_value = {"ok": True}
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
        mocked_gateway.assert_called_once()
        payload = mocked_gateway.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "send_portal_feedback")
        self.assertEqual(payload["recipient_id"], "42424242")
        self.assertEqual(payload["notification_kind"], "portal_feedback")
        self.assertEqual(payload["feedback_id"], fb.id)
        self.assertIn("1 000 000", payload["text"])

    @patch("apps.modules.feedback.views.post_messaging_gateway")
    def test_submit_skips_telegram_without_chat(self, mocked_gateway):
        res = self.client.post(
            "/api/feedback/submissions/",
            {"kind": "error", "body": "Bug"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.data["delivery"]["status"], "skipped")
        mocked_gateway.assert_not_called()
        fb = PortalFeedback.objects.get()
        self.assertEqual(fb.delivery_status, PortalFeedback.DELIVERY_SKIPPED)
