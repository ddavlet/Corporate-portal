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

