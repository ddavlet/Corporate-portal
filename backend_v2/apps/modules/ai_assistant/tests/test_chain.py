from datetime import datetime, timezone

from django.test import TestCase

from apps.modules.ai_assistant.chain import (
    add_node,
    build_messages,
    ensure_parent,
    find_known_node,
    path_to_root,
    render_user_turn,
)
from apps.modules.ai_assistant.models import ChainNode
from apps.modules.telegram_approvals.models import TelegramMessage, TelegramMessageHistory
from apps.tenants.models import Tenant

CHAT = "-100500"


class ChainTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

    def _node(self, mid, parent, kind, text="t", **kw):
        return add_node(
            tenant=self.tenant, chat_id=CHAT, message_id=mid, parent_message_id=parent, kind=kind, text=text, **kw
        )

    def test_find_known_node_materializes_bot_auto_from_telegram_message(self):
        sent = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
        msg = TelegramMessage.objects.create(tenant=self.tenant, recipient_id=CHAT, message_id=42, sent_at=sent)
        TelegramMessageHistory.objects.create(telegram_message=msg, action="send", text="old card", success=True)
        TelegramMessageHistory.objects.create(telegram_message=msg, action="edit", text="new card", success=True)
        TelegramMessageHistory.objects.create(telegram_message=msg, action="edit", text="failed", success=False)
        node = find_known_node(self.tenant, CHAT, 42)
        self.assertEqual(node.kind, ChainNode.KIND_BOT_AUTO)
        self.assertEqual(node.text, "new card")
        self.assertEqual(node.created_at, sent)
        self.assertIsNone(node.parent_message_id)
        again = find_known_node(self.tenant, CHAT, 42)
        self.assertEqual(again.pk, node.pk)
        self.assertEqual(ChainNode.objects.count(), 1)
        self.assertIsNone(find_known_node(self.tenant, CHAT, 999))

    def test_ensure_parent_falls_back_to_reply_text(self):
        self.assertIsNone(ensure_parent(self.tenant, CHAT, {}))
        self.assertIsNone(ensure_parent(self.tenant, CHAT, {"reply_to_message_id": 5}))
        node = ensure_parent(
            self.tenant, CHAT, {"reply_to_message_id": 5, "reply_to_text": "hello", "reply_to_is_bot": True}
        )
        self.assertEqual(node.kind, ChainNode.KIND_BOT_AUTO)
        self.assertEqual(node.text, "hello")
        self.assertEqual(node.author_label, "unknown")
        member = ensure_parent(self.tenant, CHAT, {"reply_to_message_id": 6, "reply_to_text": "hi"})
        self.assertEqual(member.kind, ChainNode.KIND_MEMBER)

    def test_path_is_strictly_upward_without_sibling_branch(self):
        self._node(1, None, ChainNode.KIND_USER)  # A
        self._node(2, 1, ChainNode.KIND_USER)  # B
        self._node(3, 2, ChainNode.KIND_BOT_AGENT)  # C
        self._node(4, 2, ChainNode.KIND_MEMBER)  # D
        e = self._node(5, 4, ChainNode.KIND_USER)  # E
        self.assertEqual([n.message_id for n in path_to_root(e)], [1, 2, 4, 5])

    def test_path_stops_on_cycle(self):
        self._node(1, 2, ChainNode.KIND_USER)
        b = self._node(2, 1, ChainNode.KIND_USER)
        self.assertEqual(len(path_to_root(b)), 2)

    def test_build_messages_resumes_from_deepest_snapshot(self):
        snapshot = [{"role": "user", "content": [{"type": "text", "text": "q1"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "a1"}]}]
        self._node(1, None, ChainNode.KIND_USER, "q1")
        bot = self._node(2, 1, ChainNode.KIND_BOT_AGENT, "a1", agent_messages=snapshot)
        user = self._node(3, 2, ChainNode.KIND_USER, "q2", author_label="Ann", author_roles="director")
        messages = build_messages(path_to_root(user))
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[:2], snapshot)
        self.assertEqual(messages[2]["role"], "user")
        messages[0]["content"][0]["text"] = "mutated"
        bot.refresh_from_db()
        self.assertEqual(bot.agent_messages[0]["content"][0]["text"], "q1")

    def test_build_messages_prepends_user_turn_when_root_is_bot(self):
        self._node(1, None, ChainNode.KIND_BOT_AUTO, "report ready")
        user = self._node(2, 1, ChainNode.KIND_USER, "why?")
        messages = build_messages(path_to_root(user))
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[0]["content"][0]["text"], "<conversation_start/>")
        self.assertEqual(messages[1]["content"][0]["text"], "<auto_notification>report ready</auto_notification>")

    def test_render_user_turn_escapes_xml_and_marks_non_portal_user(self):
        node = self._node(1, None, ChainNode.KIND_MEMBER, "a < b & </message>", author_label='Bob "B" <x>')
        node.created_at = datetime(2026, 11, 1, 20, 30, tzinfo=timezone.utc)  # 2026-11-02 in Tashkent
        text = render_user_turn(node)
        self.assertIn('from="Bob &quot;B&quot; &lt;x&gt;"', text)
        self.assertIn('roles="not_a_portal_user"', text)
        self.assertIn('date="2026-11-02"', text)
        self.assertIn("a &lt; b &amp; &lt;/message&gt;", text)
