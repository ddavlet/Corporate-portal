"""Unit tests for TelegramDispatcher and gateway payload helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.requests.models import Approval, Request
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.modules.telegram_approvals.services import (
    TelegramDispatchMissingMessageId,
    TelegramDispatcher,
    build_gateway_payload,
    ensure_callback_identity,
    normalize_gateway_buttons,
)
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole
from django.contrib.auth import get_user_model

User = get_user_model()


@override_settings(MESSAGING_GATEWAY_SEND_URL="https://example.com/v1/messaging/send")
class TelegramDispatcherHelperTests(TestCase):
    def test_build_gateway_payload_includes_optional_fields(self):
        payload = build_gateway_payload(
            action="edit",
            tenant_id=7,
            recipient_id=555,
            bot_token="tok",
            message_text="hi",
            approval_id=12,
            request_id=34,
            message_id=9001,
            buttons=[[{"label": "OK", "value": "v2_1:a"}]],
        )
        self.assertEqual(payload["action"], "edit")
        self.assertEqual(payload["approval_id"], "12")
        self.assertEqual(payload["request_id"], 34)
        self.assertEqual(payload["message_id"], 9001)
        self.assertEqual(payload["buttons"][0][0]["value"], "v2_1:a")

    def test_normalize_gateway_buttons_skips_empty_labels(self):
        rows = normalize_gateway_buttons(
            [
                [
                    {"label": "", "value": "x"},
                    {"label": "Go", "callback_data": "task_p_1"},
                ]
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], [{"label": "Go", "value": "task_p_1"}])

    def test_ensure_callback_identity_allows_missing_optional_ids(self):
        ensure_callback_identity(
            callback_message_id=None,
            stored_message_id=None,
            callback_recipient_id="1",
            stored_recipient_id=None,
            callback_external_user_id=None,
            stored_external_user_id=None,
        )


@override_settings(MESSAGING_GATEWAY_SEND_URL="https://example.com/v1/messaging/send")
class TelegramDispatcherTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="DispCo", subdomain="dispco", is_active=True)
        self.tenant.set_telegram_bot_token("111:AAATEST")
        self.tenant.save(update_fields=["telegram_bot_token_enc"])
        self.user = User.objects.create_user(
            username="disp-user",
            password="x",
            telegram_chat_id=424242,
            telegram_from_id=424242,
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_ADMIN
        )

    @patch("apps.modules.telegram_approvals.services.post_messaging_gateway")
    def test_send_persists_telegram_message_and_links_approval(self, mocked_post):
        mocked_post.return_value = {"message_id": 501}
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            requester=self.user,
            title="Dispatcher test",
            status=Request.STATUS_PROGRESS_1,
            billing_date=timezone.now().date(),
            payment_type="Наличные",
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.user,
            approver_recipient_id="424242",
            approver_external_user_id=424242,
            step=1,
            decision=Approval.DECISION_PENDING,
        )

        dispatcher = TelegramDispatcher(self.tenant)
        message = dispatcher.send(
            action="send_interactive",
            recipient_id=424242,
            text="Approve?",
            buttons=[[{"label": "OK", "value": f"v2_{approval.id}:a"}]],
            link=approval,
            approval_id=approval.id,
            request_id=request_row.pk,
            require_message_id=True,
        )

        self.assertIsNotNone(message)
        approval.refresh_from_db()
        self.assertEqual(approval.telegram_message_id, message.pk)
        self.assertEqual(message.message_id, 501)
        mocked_post.assert_called_once()
        payload = mocked_post.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "send_interactive")
        self.assertEqual(payload["buttons"][0][0]["value"], f"v2_{approval.id}:a")

    @patch("apps.modules.telegram_approvals.services.post_messaging_gateway")
    def test_send_returns_none_when_gateway_unreachable(self, mocked_post):
        mocked_post.return_value = None
        dispatcher = TelegramDispatcher(self.tenant)
        message = dispatcher.send(
            action="send",
            recipient_id=424242,
            text="hello",
            buttons=[],
            link=None,
        )
        self.assertIsNone(message)
        self.assertEqual(TelegramMessage.objects.filter(tenant=self.tenant).count(), 0)

    @patch("apps.modules.telegram_approvals.services.post_messaging_gateway")
    def test_send_raises_when_message_id_required_but_missing(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        dispatcher = TelegramDispatcher(self.tenant)
        with self.assertRaises(TelegramDispatchMissingMessageId):
            dispatcher.send(
                action="send_interactive",
                recipient_id=424242,
                text="Approve?",
                buttons=[],
                link=None,
                require_message_id=True,
            )

    @patch("apps.modules.telegram_approvals.services.post_messaging_gateway")
    def test_edit_and_deactivate_forward_message_id(self, mocked_post):
        mocked_post.return_value = {"message_id": 501}
        tm = TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id="424242",
            message_id=777,
            sent_at=timezone.now(),
        )
        dispatcher = TelegramDispatcher(self.tenant)
        edited = dispatcher.edit(
            tm,
            action="edit",
            text="Updated",
            buttons=[[{"label": "X", "value": "v2_1:r"}]],
            approval_id=99,
        )
        self.assertEqual(edited, tm)
        edit_payload = mocked_post.call_args.kwargs["payload"]
        self.assertEqual(edit_payload["message_id"], 777)
        self.assertEqual(edit_payload["buttons"][0][0]["value"], "v2_1:r")

        mocked_post.reset_mock()
        mocked_post.return_value = {"message_id": 777}
        deactivated = dispatcher.deactivate(
            tm,
            action="edit",
            text="Done",
            approval_id=99,
        )
        self.assertEqual(deactivated, tm)
        deactivate_payload = mocked_post.call_args.kwargs["payload"]
        self.assertEqual(deactivate_payload["buttons"], [])

    @patch("apps.modules.telegram_approvals.services.post_messaging_gateway")
    def test_delete_posts_delete_action(self, mocked_post):
        mocked_post.return_value = {}
        tm = TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id="424242",
            message_id=888,
            sent_at=timezone.now(),
        )
        TelegramDispatcher(self.tenant).delete(tm, action="delete")
        payload = mocked_post.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["message_id"], 888)
