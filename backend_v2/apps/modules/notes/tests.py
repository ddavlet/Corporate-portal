from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import patch

from apps.tenants.models import Tenant
from apps.modules.notes.models import Note
from apps.modules.notes.views import _send_note_via_gateway


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

    @patch("apps.modules.telegram_approvals.services.post_messaging_gateway")
    def test_send_note_via_gateway_uses_transport_payload_helper(self, mocked_gateway):
        mocked_gateway.return_value = {"ok": True}
        sent = _send_note_via_gateway(
            bot_token="token",
            chat_id=12345,
            text="hello",
            tenant=self.tenant,
        )
        self.assertTrue(sent)
        payload = mocked_gateway.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "send")
        self.assertEqual(payload["recipient_id"], "12345")
        self.assertEqual(payload["buttons"], [])

