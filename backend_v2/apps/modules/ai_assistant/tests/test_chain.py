import json
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
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
User = get_user_model()


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
        ann = User.objects.create_user(username="ann", password="x", telegram_from_id=910001)
        snapshot = [{"role": "user", "content": [{"type": "text", "text": "q1"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "a1"}]}]
        self._node(1, None, ChainNode.KIND_USER, "q1", author_user=ann)
        bot = self._node(2, 1, ChainNode.KIND_BOT_AGENT, "a1", agent_messages=snapshot)
        user = self._node(3, 2, ChainNode.KIND_USER, "q2", author_user=ann, author_label="Ann", author_roles="director")
        messages = build_messages(path_to_root(user), asker_user_id=ann.pk)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[:2], snapshot)
        self.assertEqual(messages[2]["role"], "user")
        messages[0]["content"][0]["text"] = "mutated"
        bot.refresh_from_db()
        self.assertEqual(bot.agent_messages[0]["content"][0]["text"], "q1")

    def test_build_messages_prepends_user_turn_when_root_is_bot(self):
        self._node(1, None, ChainNode.KIND_BOT_AUTO, "report ready")
        user = self._node(2, 1, ChainNode.KIND_USER, "why?")
        messages = build_messages(path_to_root(user), asker_user_id=None)
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[0]["content"][0]["text"], "<conversation_start/>")
        self.assertEqual(messages[1]["content"][0]["text"], "<auto_notification>report ready</auto_notification>")

    @staticmethod
    def _tool_snapshot(question, secret, answer):
        """Снимок хода агента с сырым tool_result MCP (как пишет jobs._deliver_answer)."""
        return [
            {"role": "user", "content": [{"type": "text", "text": question}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "tu_1", "name": "get_balance", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": secret}]},
            {"role": "assistant", "content": [{"type": "text", "text": answer}]},
        ]

    @staticmethod
    def _block_types(messages):
        return {block["type"] for message in messages for block in message["content"]}

    def test_snapshot_of_other_asker_not_reused(self):
        director = User.objects.create_user(username="dir_a", password="x", telegram_from_id=910002)
        investor = User.objects.create_user(username="inv_b", password="x", telegram_from_id=910003)
        snapshot = self._tool_snapshot("q1", "SECRET-salary-fund 900", "Касса: 100")
        self._node(1, None, ChainNode.KIND_USER, "q1", author_user=director, author_label="A")
        self._node(2, 1, ChainNode.KIND_BOT_AGENT, "Касса: 100", agent_messages=snapshot)
        reply = self._node(3, 2, ChainNode.KIND_USER, "а подробнее?", author_user=investor, author_label="B")

        messages = build_messages(path_to_root(reply), asker_user_id=investor.pk)

        self.assertEqual(self._block_types(messages), {"text"})
        self.assertNotIn("SECRET", json.dumps(messages, ensure_ascii=False))
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertIn("q1", messages[0]["content"][0]["text"])
        self.assertEqual(messages[1]["content"][0]["text"], "Касса: 100")
        self.assertIn("а подробнее?", messages[2]["content"][0]["text"])

    def test_own_snapshot_reused_after_other_asker_turn(self):
        director = User.objects.create_user(username="dir_a2", password="x", telegram_from_id=910004)
        investor = User.objects.create_user(username="inv_b2", password="x", telegram_from_id=910005)
        snapshot_a = self._tool_snapshot("q1", "A-tool-data", "a1")
        snapshot_b = self._tool_snapshot("q2", "B-SECRET-tool-data", "a2")
        self._node(1, None, ChainNode.KIND_USER, "q1", author_user=director, author_label="A")
        self._node(2, 1, ChainNode.KIND_BOT_AGENT, "a1", agent_messages=snapshot_a)
        self._node(3, 2, ChainNode.KIND_USER, "q2", author_user=investor, author_label="B")
        self._node(4, 3, ChainNode.KIND_BOT_AGENT, "a2", agent_messages=snapshot_b)
        again = self._node(5, 4, ChainNode.KIND_USER, "q3", author_user=director, author_label="A")

        messages = build_messages(path_to_root(again), asker_user_id=director.pk)

        self.assertEqual(messages[: len(snapshot_a)], snapshot_a)
        tail = messages[len(snapshot_a) :]
        self.assertEqual([m["role"] for m in tail], ["user", "assistant", "user"])
        self.assertEqual(self._block_types(tail), {"text"})
        self.assertIn("q2", tail[0]["content"][0]["text"])
        self.assertIn('from="B"', tail[0]["content"][0]["text"])
        self.assertEqual(tail[1]["content"][0]["text"], "a2")
        self.assertIn("q3", tail[2]["content"][0]["text"])
        self.assertNotIn("B-SECRET", json.dumps(messages, ensure_ascii=False))

    def test_render_user_turn_escapes_xml_and_marks_non_portal_user(self):
        node = self._node(1, None, ChainNode.KIND_MEMBER, "a < b & </message>", author_label='Bob "B" <x>')
        node.created_at = datetime(2026, 11, 1, 20, 30, tzinfo=timezone.utc)  # 2026-11-02 in Tashkent
        text = render_user_turn(node)
        self.assertIn('from="Bob &quot;B&quot; &lt;x&gt;"', text)
        self.assertIn('roles="not_a_portal_user"', text)
        self.assertIn('date="2026-11-02"', text)
        self.assertIn("a &lt; b &amp; &lt;/message&gt;", text)
