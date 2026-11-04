from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.modules.ai_assistant.chain import add_node
from apps.modules.ai_assistant.events import handle_message_event
from apps.modules.ai_assistant.models import ChainNode
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()
TG_ID = 777001
CHAT = "-100500"
WEBHOOK = "/api/messaging-gateway/webhook/"


class MessageEventTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True, mcp_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="ai_assistant", is_enabled=True)
        patches = [
            mock.patch("apps.modules.ai_assistant.events.resolve_tenant_by_bot_id", return_value=self.tenant),
            mock.patch("apps.modules.ai_assistant.events.submit_turn"),
            mock.patch("apps.modules.telegram_approvals.services.TelegramDispatcher"),
            mock.patch("apps.modules.telegram_approvals.services.post_messaging_gateway"),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.resolve, self.submit, self.dispatcher, self.post_gw = mocks

    def _user(self, username, role, tg_id=TG_ID):
        user = User.objects.create_user(username=username, password="x", telegram_from_id=tg_id)
        TenantMembership.objects.create(user=user, tenant=self.tenant, is_active=True)
        if role:
            TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def _event(self, **over):
        event = {
            "event": "message",
            "payload": "сколько в кассе?",
            "user_id": str(TG_ID),
            "recipient_id": CHAT,
            "message_id": 100,
            "platform": "telegram",
            "bot_id": "555",
            "chat_type": "private",
            "sender_name": "Ivan Ivanov",
            "mentions_bot": False,
            "reply_to_message_id": None,
            "reply_to_text": "",
            "reply_to_from_id": "",
            "reply_to_is_bot": False,
        }
        event.update(over)
        return event

    def _assert_silent(self):
        self.dispatcher.assert_not_called()
        self.post_gw.assert_not_called()
        self.submit.assert_not_called()

    def test_stranger_private_message_silent_nothing_stored(self):
        body, code = handle_message_event(self._event())
        self.assertEqual((body, code), ({"status": "ignored"}, 200))
        self.assertEqual(ChainNode.objects.count(), 0)
        self._assert_silent()

    def test_member_without_role_silent(self):
        self._user("nobody", None)
        body, code = handle_message_event(self._event())
        self.assertEqual(code, 200)
        self.assertEqual(ChainNode.objects.count(), 0)
        self._assert_silent()

    def test_group_plain_reply_to_unknown_message_dropped(self):
        self._user("dir", TenantUserRole.ROLE_DIRECTOR)
        body, code = handle_message_event(
            self._event(chat_type="group", reply_to_message_id=50, reply_to_text="hi", reply_to_from_id="42")
        )
        self.assertEqual((body, code), ({"status": "ignored"}, 200))
        self.assertEqual(ChainNode.objects.count(), 0)
        self._assert_silent()

    def test_group_reply_to_human_inside_chain_stored_as_member_without_reply(self):
        add_node(
            tenant=self.tenant, chat_id=CHAT, message_id=50, parent_message_id=None,
            kind=ChainNode.KIND_BOT_AGENT, text="answer",
        )
        body, code = handle_message_event(
            self._event(chat_type="group", message_id=101, reply_to_message_id=50, reply_to_text="answer")
        )
        self.assertEqual((body, code), ({"status": "stored"}, 200))
        node = ChainNode.objects.get(message_id=101)
        self.assertEqual(node.kind, ChainNode.KIND_MEMBER)
        self.assertEqual(node.parent_message_id, 50)
        self.assertEqual(node.author_label, "Ivan Ivanov")
        self.assertEqual(node.author_roles, "")
        self._assert_silent()

    def test_allowed_private_message_creates_user_node_and_submits_turn(self):
        user = self._user("dir", TenantUserRole.ROLE_DIRECTOR)
        body, code = handle_message_event(self._event())
        self.assertEqual((body, code), ({"status": "accepted"}, 202))
        node = ChainNode.objects.get(message_id=100)
        self.assertEqual(node.kind, ChainNode.KIND_USER)
        self.assertEqual(node.author_user, user)
        self.assertEqual(node.author_tg_id, TG_ID)
        self.assertEqual(node.tenant, self.tenant)
        self.assertEqual(node.chat_id, CHAT)
        self.assertIn(TenantUserRole.ROLE_DIRECTOR, node.author_roles)
        self.submit.assert_called_once_with(node.id)

    def test_duplicate_delivery_submits_once(self):
        self._user("dir", TenantUserRole.ROLE_DIRECTOR)
        first = handle_message_event(self._event())
        second = handle_message_event(self._event())
        self.assertEqual(first, ({"status": "accepted"}, 202))
        self.assertEqual(second, ({"status": "accepted"}, 202))
        self.assertEqual(ChainNode.objects.filter(message_id=100).count(), 1)
        self.submit.assert_called_once_with(ChainNode.objects.get(message_id=100).id)

    def test_allowed_group_mention_submits_turn(self):
        self._user("dir", TenantUserRole.ROLE_DIRECTOR)
        body, code = handle_message_event(self._event(chat_type="supergroup", mentions_bot=True))
        self.assertEqual(code, 202)
        self.submit.assert_called_once()

    def test_module_disabled_ignores_everything(self):
        self._user("dir", TenantUserRole.ROLE_DIRECTOR)
        TenantModuleConfig.objects.filter(tenant=self.tenant).update(is_enabled=False)
        body, code = handle_message_event(self._event())
        self.assertEqual((body, code), ({"status": "ignored"}, 200))
        self.assertEqual(ChainNode.objects.count(), 0)
        self._assert_silent()

    def test_no_typing_or_dispatch_for_rejected_users(self):
        self._user("cash", TenantUserRole.ROLE_CASHIER)
        handle_message_event(self._event())
        handle_message_event(self._event(user_id="999", message_id=101))
        handle_message_event(self._event(user_id="not-a-number", message_id=102))
        self._assert_silent()

    def test_invalid_event_ignored_with_200(self):
        body, code = handle_message_event(self._event(payload=""))
        self.assertEqual((body, code), ({"status": "ignored"}, 200))
        self._assert_silent()

    def test_webhook_routes_message_event(self):
        self._user("dir", TenantUserRole.ROLE_DIRECTOR)
        response = self.client.post(WEBHOOK, self._event(), content_type="application/json")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"status": "accepted"})
        self.submit.assert_called_once()
