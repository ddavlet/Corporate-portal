from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from unittest.mock import patch

from rest_framework.test import APITestCase

from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.notes.models import Note
from apps.modules.notes.views import _send_note_via_gateway
from apps.modules.requests.models import Request


User = get_user_model()


class NotesSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.sender = User.objects.create_user(username="sender", password="x")
        self.recipient = User.objects.create_user(username="recipient", password="x")

    def test_can_create_note(self):
        obj = Note.objects.create(
            tenant=self.tenant,
            created_by=self.sender,
            recipient_user=self.recipient,
            target_type=Note.TARGET_REQUEST,
            target_id=1,
            message="Hello",
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(Note.objects.filter(tenant=self.tenant).count(), 1)

    @patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
    def test_send_note_via_gateway_uses_dispatcher(self, mocked_send):
        from apps.modules.telegram_approvals.models import TelegramMessage
        from django.utils import timezone
        tm = TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id="12345",
            message_id=1,
            sent_at=timezone.now(),
        )
        mocked_send.return_value = tm
        sent = _send_note_via_gateway(
            bot_token="token",
            chat_id=12345,
            text="hello",
            tenant=self.tenant,
        )
        self.assertTrue(sent)
        mocked_send.assert_called_once()
        call_kw = mocked_send.call_args.kwargs
        self.assertEqual(call_kw["action"], "send")
        self.assertEqual(call_kw["recipient_id"], 12345)
        self.assertEqual(call_kw["buttons"], [])


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class NotesApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.sender = User.objects.create_user(username="sender_api", password="x")
        self.recipient = User.objects.create_user(username="recipient_api", password="x")
        # Recipient needs a telegram_chat_id, otherwise the serializer rejects it.
        self.recipient.telegram_chat_id = 99999
        self.recipient.save()

        TenantMembership.objects.create(tenant=self.tenant, user=self.sender, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=self.recipient, is_active=True)
        # Sender needs a role granting the "requests" module — notes on a request
        # target check has_effective_module_access("requests") in NoteCreateSerializer.
        TenantUserRole.objects.create(tenant=self.tenant, user=self.sender, role=TenantUserRole.ROLE_REQUESTER)

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="notes", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        self.request_obj = Request.objects.create(
            tenant=self.tenant,
            created_by=self.sender,
            billing_date=timezone.now().date(),
        )

        self.host = "acme.example.com"

    @patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send")
    def test_create_note_returns_201(self, mock_send):
        from apps.modules.telegram_approvals.models import TelegramMessage
        from django.utils import timezone

        tm = TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id=str(self.recipient.telegram_chat_id),
            message_id=42,
            sent_at=timezone.now(),
        )
        mock_send.return_value = tm

        self.client.force_authenticate(self.sender)
        payload = {
            "recipient_user": self.recipient.id,
            "target_type": Note.TARGET_REQUEST,
            "target_id": self.request_obj.id,
            "message": "Test note message",
        }
        res = self.client.post("/api/notes/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(Note.objects.filter(tenant=self.tenant, message="Test note message").exists())

    def test_create_note_unauthenticated_returns_401(self):
        payload = {
            "recipient_user": self.recipient.id,
            "target_type": Note.TARGET_REQUEST,
            "target_id": self.request_obj.id,
            "message": "Should fail",
        }
        res = self.client.post("/api/notes/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 401)

    def test_recipients_list_returns_users_with_telegram(self):
        no_tg_user = User.objects.create_user(username="no_telegram", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=no_tg_user, is_active=True)

        self.client.force_authenticate(self.sender)
        res = self.client.get("/api/notes/recipients/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)

        items = res.data["items"]
        returned_ids = [item["id"] for item in items]
        self.assertIn(self.recipient.id, returned_ids)
        self.assertNotIn(no_tg_user.id, returned_ids)

    def test_create_note_missing_message_returns_400(self):
        self.client.force_authenticate(self.sender)
        payload = {
            "recipient_user": self.recipient.id,
            "target_type": Note.TARGET_REQUEST,
            "target_id": self.request_obj.id,
            # "message" intentionally omitted
        }
        res = self.client.post("/api/notes/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)

