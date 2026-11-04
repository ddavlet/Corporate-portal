from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.modules.ai_assistant import jobs
from apps.modules.ai_assistant.agent import AgentOutcome, TurnUsage
from apps.modules.ai_assistant.chain import add_node
from apps.modules.ai_assistant.mcp_client import ToolSpec
from apps.modules.ai_assistant.models import ChainNode, PendingConfirmation, UsageRecord
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()
TG_ID = 777001
CHAT = "-100500"


class FakeSession:
    async def list_tools(self):
        return [ToolSpec(name="create_request", description="Создать заявку\nПодробности", input_schema={}, read_only=False)]


@asynccontextmanager
async def fake_open_mcp(*, tenant_subdomain, token):
    fake_open_mcp.calls.append((tenant_subdomain, token))
    yield FakeSession()


fake_open_mcp.calls = []


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _usage(model="claude-sonnet-5-5"):
    return TurnUsage(
        input_tokens=10, output_tokens=5, cache_read_tokens=2, cache_creation_tokens=1,
        cost_usd=Decimal("0.001"), mcp_calls=3, model=model,
    )


class JobsTests(TestCase):
    def setUp(self):
        fake_open_mcp.calls = []
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True, mcp_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="ai_assistant", is_enabled=True)
        self.user = User.objects.create_user(username="boss", password="x", telegram_from_id=TG_ID)
        TenantMembership.objects.create(user=self.user, tenant=self.tenant, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role="director")
        self.node = add_node(
            tenant=self.tenant, chat_id=CHAT, message_id=100, parent_message_id=None,
            kind=ChainNode.KIND_USER, text="сколько в кассе?", author_user=self.user,
            author_tg_id=TG_ID, author_label="Boss", author_roles="director",
        )
        # Внутри TestCase close_old_connections закрыл бы тестовое соединение с БД.
        self.close_conn = mock.Mock()
        p = mock.patch.object(jobs, "close_old_connections", self.close_conn)
        p.start()
        self.addCleanup(p.stop)
        self.run_agent = mock.AsyncMock()
        self.send_answer = mock.Mock(return_value=[SimpleNamespace(message_id=200)])
        self.send_confirmation = mock.Mock()
        self.send_typing = mock.Mock()
        self.mint = mock.Mock(return_value="tok")
        patches = {
            "run_agent": self.run_agent,
            "open_mcp": fake_open_mcp,
            "mint_mcp_access_token": self.mint,
            "send_typing": self.send_typing,
            "send_answer": self.send_answer,
            "send_confirmation": self.send_confirmation,
            "AsyncAnthropic": FakeClient,
        }
        for name, value in patches.items():
            p = mock.patch.object(jobs, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _answer(self, text="В кассе 100"):
        return AgentOutcome(kind="answer", messages=[{"role": "user", "content": "q"}], text=text, usage=_usage())

    def test_answer_saves_bot_agent_nodes_with_snapshot_and_usage(self):
        outcome = self._answer()
        self.run_agent.return_value = outcome
        jobs.run_turn(self.node.id)
        self.send_typing.assert_called_once()
        self.assertEqual(self.close_conn.call_count, 3)
        self.send_answer.assert_called_once_with(self.tenant, CHAT, 100, "В кассе 100")
        bot = ChainNode.objects.get(tenant=self.tenant, message_id=200)
        self.assertEqual(bot.kind, ChainNode.KIND_BOT_AGENT)
        self.assertEqual(bot.parent_message_id, 100)
        self.assertEqual(bot.agent_messages, outcome.messages)
        self.assertEqual(fake_open_mcp.calls, [("acme", "tok")])
        usage = UsageRecord.objects.get()
        self.assertEqual(usage.outcome, UsageRecord.OUTCOME_ANSWERED)
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.mcp_calls), (10, 5, 3))
        self.assertEqual(usage.user, self.user)
        self.assertEqual(usage.model, "claude-sonnet-5-5")

    def test_long_answer_each_part_is_chain_node(self):
        text = ("Абзац текста. " * 40 + "\n\n") * 20
        self.run_agent.return_value = self._answer(text)
        self.send_answer.return_value = [SimpleNamespace(message_id=m) for m in (201, 202, 203)]
        jobs.run_turn(self.node.id)
        nodes = list(ChainNode.objects.filter(kind=ChainNode.KIND_BOT_AGENT).order_by("message_id"))
        self.assertEqual([n.message_id for n in nodes], [201, 202, 203])
        self.assertEqual([n.parent_message_id for n in nodes], [100, 201, 202])
        for n in nodes:
            self.assertTrue(n.text)
            self.assertEqual(n.agent_messages, [{"role": "user", "content": "q"}])

    def test_confirm_creates_pending_and_sends_buttons(self):
        calls = [{"id": "t1", "name": "create_request", "input": {"amount": 5}}]
        self.run_agent.return_value = AgentOutcome(
            kind="confirm", messages=[{"role": "user", "content": "q"}], pending_tool_calls=calls, usage=_usage()
        )
        tg = TelegramMessage.objects.create(tenant=self.tenant, recipient_id=CHAT, message_id=300)
        self.send_confirmation.return_value = tg
        jobs.run_turn(self.node.id)
        pending = PendingConfirmation.objects.get()
        self.assertEqual(pending.status, PendingConfirmation.STATUS_PENDING)
        self.assertEqual(pending.tool_calls, calls)
        self.assertEqual(pending.confirmation_message, tg)
        self.assertEqual(pending.requester_user, self.user)
        self.assertEqual(pending.origin_message_id, 100)
        args = self.send_confirmation.call_args.args
        self.assertEqual(args[:4], (self.tenant, CHAT, 100, pending.pk))
        self.assertIn("Создать заявку", args[4])
        self.assertNotIn("Подробности", args[4])
        node = ChainNode.objects.get(message_id=300)
        self.assertIsNone(node.agent_messages)
        self.assertEqual(node.parent_message_id, 100)
        self.assertEqual(UsageRecord.objects.get().outcome, UsageRecord.OUTCOME_CONFIRMATION_REQUESTED)

    def test_exception_sends_error_message_and_logs(self):
        self.run_agent.side_effect = RuntimeError("boom")
        with self.assertLogs(jobs.logger, level="ERROR"):
            jobs.run_turn(self.node.id)
        self.send_answer.assert_called_once_with(self.tenant, CHAT, 100, jobs.ERROR_TEXT)
        self.assertEqual(UsageRecord.objects.get().outcome, UsageRecord.OUTCOME_ERROR)
        node = ChainNode.objects.get(kind=ChainNode.KIND_BOT_AGENT)
        self.assertEqual((node.message_id, node.parent_message_id), (200, 100))
        self.assertIsNone(node.agent_messages)
        self.assertFalse(ChainNode.objects.filter(kind=ChainNode.KIND_BOT_AGENT, agent_messages__isnull=False).exists())

    def test_agent_error_outcome_sends_error_without_snapshot(self):
        self.run_agent.return_value = AgentOutcome(kind="error", messages=[{"x": 1}], usage=_usage())
        jobs.run_turn(self.node.id)
        self.send_answer.assert_called_once_with(self.tenant, CHAT, 100, jobs.ERROR_TEXT)
        self.assertFalse(ChainNode.objects.filter(agent_messages__isnull=False, kind=ChainNode.KIND_BOT_AGENT).exists())
        usage = UsageRecord.objects.get()
        self.assertEqual(usage.outcome, UsageRecord.OUTCOME_ERROR)
        self.assertEqual(usage.input_tokens, 10)

    def test_refusal_message(self):
        self.run_agent.return_value = AgentOutcome(kind="refused", messages=[], usage=_usage())
        jobs.run_turn(self.node.id)
        self.send_answer.assert_called_once_with(self.tenant, CHAT, 100, jobs.REFUSED_TEXT)
        self.assertEqual(UsageRecord.objects.get().outcome, UsageRecord.OUTCOME_REFUSED)

    def test_answer_not_delivered_records_error_and_sends_error_text(self):
        self.run_agent.return_value = self._answer()
        self.send_answer.side_effect = [[], [SimpleNamespace(message_id=210)]]
        jobs.run_turn(self.node.id)
        self.assertEqual(self.send_answer.call_count, 2)
        self.assertEqual(self.send_answer.call_args.args[3], jobs.ERROR_TEXT)
        self.assertEqual(UsageRecord.objects.get().outcome, UsageRecord.OUTCOME_ERROR)

    def test_partial_delivery_records_error_keeps_sent_nodes(self):
        text = ("Абзац текста. " * 40 + "\n\n") * 20
        self.run_agent.return_value = self._answer(text)
        self.send_answer.return_value = [SimpleNamespace(message_id=201)]
        jobs.run_turn(self.node.id)
        self.assertEqual(self.send_answer.call_count, 1)
        self.assertEqual(list(ChainNode.objects.filter(kind=ChainNode.KIND_BOT_AGENT).values_list("message_id", flat=True)), [201])
        self.assertEqual(UsageRecord.objects.get().outcome, UsageRecord.OUTCOME_ERROR)

    def test_error_reply_is_chain_node_under_user_message(self):
        self.run_agent.side_effect = RuntimeError("boom")
        self.send_answer.return_value = [SimpleNamespace(message_id=250)]
        with self.assertLogs(jobs.logger, level="ERROR"):
            jobs.run_turn(self.node.id)
        node = ChainNode.objects.get(message_id=250)
        self.assertEqual(node.parent_message_id, 100)
        self.assertEqual(node.kind, ChainNode.KIND_BOT_AGENT)
        self.assertIsNone(node.agent_messages)
        self.assertEqual(node.text, jobs.ERROR_TEXT)

    def test_resume_uses_pending_messages_and_fresh_token(self):
        tg = TelegramMessage.objects.create(tenant=self.tenant, recipient_id=CHAT, message_id=300)
        history = [{"role": "user", "content": "q"}]
        calls = [{"id": "t1", "name": "create_request", "input": {}}]
        pending = PendingConfirmation.objects.create(
            tenant=self.tenant, chat_id=CHAT, requester_user=self.user, requester_tg_id=TG_ID,
            origin_message_id=100, confirmation_message=tg, agent_messages=history, tool_calls=calls,
            expires_at="2099-01-01T00:00:00Z",
        )
        self.mint.return_value = "fresh"
        self.run_agent.return_value = self._answer("Готово")
        self.send_answer.return_value = [SimpleNamespace(message_id=301)]
        jobs.resume_pending(pending.pk, "confirm")
        kwargs = self.run_agent.call_args.kwargs
        self.assertEqual(kwargs["messages"], history)
        self.assertEqual(kwargs["resume_tool_calls"], calls)
        self.assertEqual(kwargs["resume_decision"], "confirm")
        self.mint.assert_called_once_with(self.user, self.tenant.pk)
        self.assertEqual(fake_open_mcp.calls, [("acme", "fresh")])
        self.send_answer.assert_called_once_with(self.tenant, CHAT, 300, "Готово")
        self.assertEqual(ChainNode.objects.get(message_id=301).parent_message_id, 300)
        self.assertEqual(UsageRecord.objects.get().outcome, UsageRecord.OUTCOME_ANSWERED)

    def test_resume_silent_when_requester_lost_access(self):
        tg = TelegramMessage.objects.create(tenant=self.tenant, recipient_id=CHAT, message_id=300)
        pending = PendingConfirmation.objects.create(
            tenant=self.tenant, chat_id=CHAT, requester_user=self.user, requester_tg_id=TG_ID,
            origin_message_id=100, confirmation_message=tg, agent_messages=[], tool_calls=[],
            expires_at="2099-01-01T00:00:00Z",
        )
        TenantUserRole.objects.filter(user=self.user).delete()
        jobs.resume_pending(pending.pk, "confirm")
        self.run_agent.assert_not_called()
        self.send_answer.assert_not_called()
        self.assertEqual(UsageRecord.objects.count(), 0)
