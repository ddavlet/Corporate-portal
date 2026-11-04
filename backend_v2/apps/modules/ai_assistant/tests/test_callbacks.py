from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.modules.ai_assistant import callbacks
from apps.modules.ai_assistant.models import PendingConfirmation
from apps.modules.telegram_approvals.models import TelegramMessage, TelegramMessageHistory
from apps.tenants.models import Tenant

User = get_user_model()
TG_ID = 777001
CHAT = "-100500"
WEBHOOK = "/api/messaging-gateway/webhook/"
BASE_TEXT = "<b>Подтвердите</b>\nсоздать заявку"


class ConfirmationCallbackTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True, mcp_enabled=True)
        self.user = User.objects.create_user(username="dir", password="x", telegram_from_id=TG_ID)
        self.tg = TelegramMessage.objects.create(
            tenant=self.tenant, recipient_id=CHAT, message_id=300, sent_at=timezone.now()
        )
        TelegramMessageHistory.objects.create(
            telegram_message=self.tg, action=TelegramMessageHistory.ACTION_SEND, text=BASE_TEXT, message_id=300
        )
        self.pending = self._pending()
        patches = [
            mock.patch.object(callbacks, "resolve_tenant_by_bot_id", return_value=self.tenant),
            mock.patch.object(callbacks, "submit_resume"),
            mock.patch.object(callbacks, "TelegramDispatcher"),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.resolve, self.submit, self.dispatcher_cls = mocks
        self.deactivate = self.dispatcher_cls.return_value.deactivate

    def _pending(self, **over):
        fields = dict(
            tenant=self.tenant, chat_id=CHAT, requester_user=self.user, requester_tg_id=TG_ID,
            origin_message_id=100, confirmation_message=self.tg, agent_messages=[], tool_calls=[],
            expires_at=timezone.now() + timedelta(hours=24),
        )
        fields.update(over)
        return PendingConfirmation.objects.create(**fields)

    def _event(self, **over):
        event = {
            "event": "interaction", "payload": f"aiq:{self.pending.pk}:y", "user_id": str(TG_ID),
            "recipient_id": CHAT, "message_id": 300, "platform": "telegram", "bot_id": "555",
        }
        event.update(over)
        return event

    def _press(self, choice="y", **over):
        event = self._event(**over)
        payload = over.get("payload", f"aiq:{self.pending.pk}:{choice}")
        event["payload"] = payload
        return callbacks.handle_confirmation_callback(payload=payload, event_data=event)

    def test_requester_confirm_submits_resume_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            code, body = self._press("y")
        self.assertEqual(code, 200)
        self.submit.assert_called_once_with(self.pending.pk, "confirm")
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingConfirmation.STATUS_CONFIRMED)
        self.assertIsNotNone(self.pending.resolved_at)
        kwargs = self.deactivate.call_args.kwargs
        self.assertEqual(kwargs["text"], BASE_TEXT + "\n\n✅ Подтверждено")

    def test_double_tap_resumes_once(self):
        first = self._press("y")
        second = self._press("y")
        self.assertEqual(first[0], 200)
        self.assertEqual(second, (200, {"detail": "ignored"}))
        self.submit.assert_called_once_with(self.pending.pk, "confirm")
        self.assertEqual(self.deactivate.call_count, 1)

    def test_other_group_member_press_ignored(self):
        code, body = self._press("y", user_id="999")
        self.assertEqual((code, body), (200, {"detail": "ignored"}))
        self.submit.assert_not_called()
        self.deactivate.assert_not_called()
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingConfirmation.STATUS_PENDING)

    def test_cancel_submits_cancel(self):
        code, _ = self._press("n")
        self.assertEqual(code, 200)
        self.submit.assert_called_once_with(self.pending.pk, "cancel")
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingConfirmation.STATUS_CANCELLED)
        self.assertEqual(self.deactivate.call_args.kwargs["text"], BASE_TEXT + "\n\n❌ Отменено")

    def test_expired_marks_expired_no_resume(self):
        PendingConfirmation.objects.filter(pk=self.pending.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        code, _ = self._press("y")
        self.assertEqual(code, 200)
        self.submit.assert_not_called()
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingConfirmation.STATUS_EXPIRED)
        self.assertEqual(self.deactivate.call_args.kwargs["text"], "Запрос устарел.")

    def test_mismatched_message_id_ignored(self):
        code, body = self._press("y", message_id=999)
        self.assertEqual((code, body), (200, {"detail": "ignored"}))
        self.submit.assert_not_called()
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingConfirmation.STATUS_PENDING)

    def test_other_tenant_ignored(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        self.resolve.return_value = other
        code, body = self._press("y")
        self.assertEqual((code, body), (200, {"detail": "ignored"}))
        self.submit.assert_not_called()

    def test_bad_payload_is_202(self):
        code, _ = callbacks.handle_confirmation_callback(payload="aiq:abc:y", event_data=self._event())
        self.assertEqual(code, 202)
        self.submit.assert_not_called()

    def test_edit_failure_does_not_block_resume(self):
        self.deactivate.side_effect = RuntimeError("gateway down")
        code, _ = self._press("y")
        self.assertEqual(code, 200)
        self.submit.assert_called_once_with(self.pending.pk, "confirm")

    def test_webhook_routes_aiq_prefix(self):
        with mock.patch(
            "apps.modules.ai_assistant.callbacks.handle_confirmation_callback", return_value=(200, {"detail": "confirmed"})
        ) as handler, mock.patch(
            "apps.modules.telegram_approvals.views.TelegramApprovalWebhookView._parse_callback_data"
        ) as parse:
            response = self.client.post(WEBHOOK, self._event(), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "confirmed"})
        handler.assert_called_once()
        parse.assert_not_called()
