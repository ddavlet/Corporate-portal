import asyncio
import copy
import time
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.modules.ai_assistant.agent import CANCELLED_RESULT, run_agent
from apps.modules.ai_assistant.calculator import CALCULATOR_TOOL, CALCULATOR_TOOL_NAME
from apps.modules.ai_assistant.config import (
    AGENT_EFFORT,
    AGENT_MAX_STEPS,
    AGENT_MAX_TOKENS,
    AGENT_MODEL,
    FALLBACK_BETA,
    THINKING_BINDING_BETA,
)
from apps.modules.ai_assistant.mcp_client import (
    ClientMcpSession,
    ToolSpec,
    mint_mcp_access_token,
    tool_spec_from_mcp,
)
from apps.modules.ai_assistant.prompts import SYSTEM_PROMPT

# --- фейки ---------------------------------------------------------------


class Block:
    """Блок content в форме SDK: атрибуты + to_dict()."""

    def __init__(self, **data):
        self._data = data
        for key, value in data.items():
            setattr(self, key, value)

    def to_dict(self, **_kwargs):
        return copy.deepcopy(self._data)


def text(value):
    return Block(type="text", text=value)


def thinking():
    return Block(type="thinking", thinking="", signature="sig-123")


def tool_use(block_id, name, tool_input=None):
    return Block(type="tool_use", id=block_id, name=name, input=tool_input or {})


def response(content, stop_reason, *, model=AGENT_MODEL, input_tokens=100, output_tokens=10, iterations=None):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        stop_details=None,
        model=model,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            iterations=iterations,
        ),
    )


class FakeClient:
    """client.beta.messages.create (async), отдаёт заготовленные ответы и пишет запросы."""

    def __init__(self, responses=None, *, repeat=None, error=None):
        self.requests = []
        self._responses = list(responses or [])
        self._repeat = repeat
        self._error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        if self._error is not None:
            raise self._error
        if self._responses:
            return self._responses.pop(0)
        if self._repeat is not None:
            return self._repeat
        raise AssertionError("FakeClient: no scripted response left")


class FakeSession:
    def __init__(self, tools, results=None, *, list_error=None):
        self.tools = tools
        self.results = results or {}
        self.calls = []
        self._list_error = list_error

    async def list_tools(self):
        if self._list_error is not None:
            raise self._list_error
        return list(self.tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.get(name, (f"{name} ok", False))


READ_A = ToolSpec(name="list_requests", description="List requests", input_schema={"type": "object"}, read_only=True)
READ_B = ToolSpec(name="get_balance", description="Balances", input_schema={"type": "object"}, read_only=True)
WRITE = ToolSpec(name="create_task", description="Create task", input_schema={"type": "object"}, read_only=False)

USER_MSG = [{"role": "user", "content": [{"type": "text", "text": '<message from="A" roles="director" date="2026-11-04">hi</message>'}]}]


def run(**kwargs):
    kwargs.setdefault("messages", copy.deepcopy(USER_MSG))
    return asyncio.run(run_agent(**kwargs))


# --- цикл агента --------------------------------------------------------


class RunAgentTests(SimpleTestCase):
    def test_answer_without_tools(self):
        client = FakeClient([response([thinking(), text("Итого "), text("100 UZS")], "end_turn")])
        session = FakeSession([READ_A])

        outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(outcome.text, "Итого 100 UZS")
        self.assertEqual(outcome.pending_tool_calls, [])
        self.assertEqual(len(outcome.messages), 2)
        self.assertEqual(outcome.messages[-1]["role"], "assistant")
        self.assertEqual(session.calls, [])
        self.assertEqual(outcome.usage.input_tokens, 100)
        self.assertEqual(outcome.usage.output_tokens, 10)
        self.assertEqual(outcome.usage.model, AGENT_MODEL)
        self.assertEqual(outcome.usage.mcp_calls, 0)

    def test_read_tool_executed_and_result_appended_in_single_user_message(self):
        client = FakeClient(
            [
                response(
                    [thinking(), tool_use("tu_1", "list_requests", {"status": "new"}), tool_use("tu_2", "get_balance")],
                    "tool_use",
                ),
                response([text("Готово")], "end_turn"),
            ]
        )
        session = FakeSession([READ_A, READ_B], {"list_requests": ("[1, 2]", False), "get_balance": ("10", False)})

        outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(session.calls, [("list_requests", {"status": "new"}), ("get_balance", {})])
        self.assertEqual([m["role"] for m in outcome.messages], ["user", "assistant", "user", "assistant"])
        tool_message = outcome.messages[2]
        self.assertEqual(
            tool_message["content"],
            [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "[1, 2]", "is_error": False},
                {"type": "tool_result", "tool_use_id": "tu_2", "content": "10", "is_error": False},
            ],
        )
        # Второй запрос видит историю с результатами инструментов.
        self.assertEqual(client.requests[1]["messages"], outcome.messages[:3])
        self.assertEqual(outcome.usage.mcp_calls, 2)
        self.assertEqual(outcome.usage.input_tokens, 200)

    def test_write_tool_pauses_for_confirmation_without_executing(self):
        client = FakeClient(
            [
                response(
                    [text("Создам задачу"), tool_use("tu_r", "list_requests"), tool_use("tu_w", "create_task", {"title": "X"})],
                    "tool_use",
                )
            ]
        )
        session = FakeSession([READ_A, WRITE])

        outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "confirm")
        self.assertEqual(session.calls, [])
        self.assertEqual(
            outcome.pending_tool_calls,
            [
                {"id": "tu_r", "name": "list_requests", "input": {}},
                {"id": "tu_w", "name": "create_task", "input": {"title": "X"}},
            ],
        )
        self.assertEqual(outcome.messages[-1]["role"], "assistant")
        self.assertEqual(outcome.messages[-1]["content"][-1]["type"], "tool_use")
        self.assertEqual(len(client.requests), 1)

    def test_unannotated_tool_treated_as_write(self):
        from mcp.types import Tool, ToolAnnotations

        schema = {"type": "object", "properties": {}}
        bare = tool_spec_from_mcp(Tool(name="edit_task", description="Edit", input_schema=schema))
        hinted_false = tool_spec_from_mcp(
            Tool(name="delete_task", input_schema=schema, annotations=ToolAnnotations(read_only_hint=False))
        )
        hinted_none = tool_spec_from_mcp(
            Tool(name="add_comment", input_schema=schema, annotations=ToolAnnotations(title="Comment"))
        )
        read = tool_spec_from_mcp(
            Tool(name="list_requests", input_schema=schema, annotations=ToolAnnotations(read_only_hint=True))
        )
        self.assertFalse(bare.read_only)
        self.assertFalse(hinted_false.read_only)
        self.assertFalse(hinted_none.read_only)
        self.assertTrue(read.read_only)
        self.assertEqual(bare.description, "Edit")
        self.assertEqual(read.description, "")
        self.assertEqual(read.input_schema, schema)

        client = FakeClient([response([tool_use("tu_1", "edit_task", {"id": 1})], "tool_use")])
        session = FakeSession([bare, read])
        outcome = run(client=client, session=session)
        self.assertEqual(outcome.kind, "confirm")
        self.assertEqual(session.calls, [])

        # Инструмент, которого нет в списке MCP, тоже не выполняется молча.
        client = FakeClient([response([tool_use("tu_2", "unknown_tool")], "tool_use")])
        outcome = run(client=client, session=FakeSession([read]))
        self.assertEqual(outcome.kind, "confirm")

    def test_resume_confirm_executes_write_tool(self):
        first = run(
            client=FakeClient([response([tool_use("tu_w", "create_task", {"title": "X"})], "tool_use")]),
            session=FakeSession([WRITE]),
        )
        self.assertEqual(first.kind, "confirm")

        client = FakeClient([response([text("Задача создана")], "end_turn")])
        session = FakeSession([WRITE], {"create_task": ('{"id": 5}', False)})
        outcome = run(
            client=client,
            session=session,
            messages=first.messages,
            resume_tool_calls=first.pending_tool_calls,
            resume_decision="confirm",
        )

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(outcome.text, "Задача создана")
        self.assertEqual(session.calls, [("create_task", {"title": "X"})])
        self.assertEqual(
            outcome.messages[len(first.messages)],
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu_w", "content": '{"id": 5}', "is_error": False}],
            },
        )
        # История только дописывается.
        self.assertEqual(outcome.messages[: len(first.messages)], first.messages)
        self.assertEqual(outcome.usage.mcp_calls, 1)

    def test_resume_cancel_returns_cancelled_tool_result(self):
        pending = [
            {"id": "tu_r", "name": "list_requests", "input": {}},
            {"id": "tu_w", "name": "create_task", "input": {"title": "X"}},
        ]
        history = copy.deepcopy(USER_MSG) + [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu_r", "name": "list_requests", "input": {}},
                    {"type": "tool_use", "id": "tu_w", "name": "create_task", "input": {"title": "X"}},
                ],
            }
        ]
        client = FakeClient([response([text("Отменено")], "end_turn")])
        session = FakeSession([READ_A, WRITE], {"list_requests": ("[]", False)})

        outcome = run(
            client=client,
            session=session,
            messages=history,
            resume_tool_calls=pending,
            resume_decision="cancel",
        )

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(session.calls, [("list_requests", {})])
        self.assertEqual(
            outcome.messages[2]["content"],
            [
                {"type": "tool_result", "tool_use_id": "tu_r", "content": "[]", "is_error": False},
                {"type": "tool_result", "tool_use_id": "tu_w", "content": CANCELLED_RESULT, "is_error": True},
            ],
        )
        self.assertEqual(CANCELLED_RESULT, "Cancelled by the user.")

    def test_tool_error_passed_as_is_error(self):
        client = FakeClient(
            [
                response([tool_use("tu_1", "list_requests")], "tool_use"),
                response([text("Нет доступа к заявкам")], "end_turn"),
            ]
        )
        session = FakeSession([READ_A], {"list_requests": ("Access denied: module 'requests'", True)})

        outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(
            outcome.messages[2]["content"],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_1",
                    "content": "Access denied: module 'requests'",
                    "is_error": True,
                }
            ],
        )

    def test_tool_exception_is_tool_error_not_agent_error(self):
        class RaisingSession(FakeSession):
            async def call_tool(self, name, arguments):
                raise RuntimeError("boom")

        client = FakeClient(
            [response([tool_use("tu_1", "list_requests")], "tool_use"), response([text("ok")], "end_turn")]
        )
        with self.assertLogs("apps.modules.ai_assistant.agent", level="ERROR"):
            outcome = run(client=client, session=RaisingSession([READ_A]))
        self.assertEqual(outcome.kind, "answer")
        self.assertTrue(outcome.messages[2]["content"][0]["is_error"])
        self.assertIn("boom", outcome.messages[2]["content"][0]["content"])

    def test_empty_end_turn_is_error(self):
        client = FakeClient([response([thinking()], "end_turn")])
        with self.assertLogs("apps.modules.ai_assistant.agent", level="WARNING"):
            outcome = run(client=client, session=FakeSession([READ_A]))
        self.assertEqual(outcome.kind, "error")
        self.assertEqual(outcome.text, "")

    def test_refusal_outcome(self):
        client = FakeClient([response([], "refusal")])
        outcome = run(client=client, session=FakeSession([READ_A]))
        self.assertEqual(outcome.kind, "refused")
        self.assertEqual(outcome.text, "")
        self.assertEqual(outcome.messages[-1], {"role": "assistant", "content": []})

    def test_max_steps_returns_error(self):
        client = FakeClient(repeat=response([tool_use("tu_1", "list_requests")], "tool_use"))
        session = FakeSession([READ_A])

        with self.assertLogs("apps.modules.ai_assistant.agent", level="ERROR"):
            outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "error")
        self.assertEqual(len(client.requests), AGENT_MAX_STEPS)
        self.assertGreater(len(outcome.messages), 1)

    def test_api_error_returns_error(self):
        import anthropic
        import httpx2

        error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        with self.assertLogs("apps.modules.ai_assistant.agent", level="ERROR"):
            outcome = run(client=FakeClient(error=error), session=FakeSession([READ_A]))
        self.assertEqual(outcome.kind, "error")
        self.assertEqual(outcome.messages, USER_MSG)

    def test_mcp_list_tools_failure_returns_error(self):
        client = FakeClient([response([text("x")], "end_turn")])
        with self.assertLogs("apps.modules.ai_assistant.agent", level="ERROR"):
            outcome = run(client=client, session=FakeSession([], list_error=ConnectionError("refused")))
        self.assertEqual(outcome.kind, "error")
        self.assertEqual(client.requests, [])

    def test_request_uses_config_model_effort_and_adaptive_thinking(self):
        client = FakeClient([response([text("ok")], "end_turn")])
        run(client=client, session=FakeSession([READ_A]))

        request = client.requests[0]
        self.assertEqual(request["model"], AGENT_MODEL)
        self.assertEqual(request["max_tokens"], AGENT_MAX_TOKENS)
        self.assertEqual(
            request["thinking"],
            {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
        )
        self.assertEqual(request["output_config"], {"effort": AGENT_EFFORT})
        self.assertEqual(request["cache_control"], {"type": "ephemeral"})
        self.assertEqual(request["betas"], [FALLBACK_BETA, THINKING_BINDING_BETA])
        self.assertEqual(THINKING_BINDING_BETA, "thinking-binding-controls-2026-08-01")
        self.assertEqual(request["fallbacks"], "default")
        self.assertEqual(request["messages"], USER_MSG)

    def test_dropped_thinking_blocks_logged_with_counts_only(self):
        reply = response([text("ok")], "end_turn")
        reply.input_transformations = [
            SimpleNamespace(type="thinking_dropped", path="messages.1.content.0", reason="prefix_binding_mismatch"),
            SimpleNamespace(type="thinking_dropped", path="messages.3.content.0", reason="prefix_binding_mismatch"),
            {"type": "thinking_dropped", "path": "messages.5.content.0", "reason": "model_binding_mismatch"},
        ]
        client = FakeClient([reply])
        with self.assertLogs("apps.modules.ai_assistant.agent", level="WARNING") as logs:
            result = run(client=client, session=FakeSession([READ_A]))

        self.assertEqual(result.kind, "answer")
        warning = "\n".join(logs.output)
        self.assertIn("thinking_dropped/prefix_binding_mismatch=2", warning)
        self.assertIn("thinking_dropped/model_binding_mismatch=1", warning)
        self.assertNotIn("messages.1", warning)

    def test_tools_sorted_and_system_prompt_constant(self):
        client = FakeClient([response([text("ok")], "end_turn"), response([text("ok")], "end_turn")])
        run(client=client, session=FakeSession([WRITE, READ_A, READ_B]))
        run(client=client, session=FakeSession([READ_B, WRITE, READ_A]))

        first, second = client.requests
        self.assertEqual([t["name"] for t in first["tools"]], ["calculate", "create_task", "get_balance", "list_requests"])
        self.assertEqual(first["tools"], second["tools"])
        self.assertEqual(
            first["tools"][1],
            {"name": "create_task", "description": "Create task", "input_schema": {"type": "object"}},
        )
        self.assertEqual(
            first["system"],
            [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        )
        self.assertEqual(first["system"], second["system"])
        for section in (
            "role",
            "data_rules",
            "user_messages",
            "identity",
            "changes",
            "language",
            "telegram_format",
        ):
            self.assertIn(f"<{section}>", SYSTEM_PROMPT)
            self.assertIn(f"</{section}>", SYSTEM_PROMPT)
        self.assertNotRegex(SYSTEM_PROMPT, r"\d{4}-\d{2}-\d{2}")

    def test_calculator_tool_listed_and_sorted(self):
        client = FakeClient([response([text("ok")], "end_turn")])
        run(client=client, session=FakeSession([WRITE, READ_A, READ_B]))

        tools = client.requests[0]["tools"]
        names = [t["name"] for t in tools]
        self.assertEqual(names, sorted(names))
        self.assertIn(CALCULATOR_TOOL_NAME, names)
        self.assertEqual(next(t for t in tools if t["name"] == CALCULATOR_TOOL_NAME), CALCULATOR_TOOL)

    def test_calculator_runs_locally_without_mcp_call(self):
        client = FakeClient(
            [
                response([tool_use("tu_c", CALCULATOR_TOOL_NAME, {"expression": "0.1 + 0.2"})], "tool_use"),
                response([text("0.3")], "end_turn"),
            ]
        )
        session = FakeSession([READ_A])

        outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(session.calls, [])
        self.assertEqual(outcome.usage.mcp_calls, 0)
        self.assertEqual(
            outcome.messages[2]["content"],
            [{"type": "tool_result", "tool_use_id": "tu_c", "content": "0.3", "is_error": False}],
        )

    def test_calculator_error_returned_as_is_error(self):
        client = FakeClient(
            [
                response([tool_use("tu_c", CALCULATOR_TOOL_NAME, {"expression": "1 / 0"})], "tool_use"),
                response([tool_use("tu_d", CALCULATOR_TOOL_NAME, {})], "tool_use"),
                response([text("done")], "end_turn"),
            ]
        )
        session = FakeSession([READ_A])

        outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "answer")
        first, second = outcome.messages[2]["content"][0], outcome.messages[4]["content"][0]
        self.assertEqual((first["content"], first["is_error"]), ("Division by zero", True))
        self.assertTrue(second["is_error"])
        self.assertEqual(session.calls, [])

    def test_calculator_does_not_trigger_confirmation(self):
        client = FakeClient(
            [
                response([tool_use("tu_c", CALCULATOR_TOOL_NAME, {"expression": "2 + 2"})], "tool_use"),
                response([text("4")], "end_turn"),
            ]
        )

        outcome = run(client=client, session=FakeSession([WRITE]))

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(len(client.requests), 2)

    def test_calculator_executed_on_resume_confirm_and_cancel(self):
        calls = [
            {"id": "tu_c", "name": CALCULATOR_TOOL_NAME, "input": {"expression": "1 + 1"}},
            {"id": "tu_w", "name": "create_task", "input": {}},
        ]
        for decision, write_result in (("confirm", ("create_task ok", False)), ("cancel", (CANCELLED_RESULT, True))):
            with self.subTest(decision=decision):
                client = FakeClient([response([text("ok")], "end_turn")])
                session = FakeSession([WRITE])
                outcome = run(
                    client=client,
                    session=session,
                    resume_tool_calls=calls,
                    resume_decision=decision,
                )
                results = outcome.messages[1]["content"]
                self.assertEqual(results[0]["content"], "2")
                self.assertFalse(results[0]["is_error"])
                self.assertEqual((results[1]["content"], results[1]["is_error"]), write_result)
                self.assertEqual(outcome.usage.mcp_calls, 1 if decision == "confirm" else 0)

    def test_mcp_tool_named_calculate_is_replaced_by_local_one(self):
        shadow = ToolSpec(name=CALCULATOR_TOOL_NAME, description="remote", input_schema={"type": "object"}, read_only=False)
        client = FakeClient([response([tool_use("tu_c", CALCULATOR_TOOL_NAME, {"expression": "1 + 1"})], "tool_use"), response([text("2")], "end_turn")])
        session = FakeSession([shadow])

        with self.assertLogs("apps.modules.ai_assistant.agent", level="WARNING") as logs:
            outcome = run(client=client, session=session)

        self.assertEqual(outcome.kind, "answer")
        self.assertEqual(session.calls, [])
        self.assertEqual([t["name"] for t in client.requests[0]["tools"]], [CALCULATOR_TOOL_NAME])
        self.assertEqual(client.requests[0]["tools"][0]["description"], CALCULATOR_TOOL["description"])
        self.assertEqual(len(logs.output), 1)

    def test_system_prompt_has_answer_style_and_calculations(self):
        for section in ("answer_style", "calculations"):
            self.assertIn(f"<{section}>", SYSTEM_PROMPT)
            self.assertIn(f"</{section}>", SYSTEM_PROMPT)
        self.assertIn("calculate tool", SYSTEM_PROMPT)
        self.assertTrue(SYSTEM_PROMPT.isascii())
        self.assertNotRegex(SYSTEM_PROMPT, r"\d{4}-\d{2}-\d{2}")
        self.assertNotRegex(SYSTEM_PROMPT, r"\d{1,2}\.\d{1,2}\.\d{2,4}")

    def test_assistant_content_appended_unchanged(self):
        fallback = Block(
            type="fallback",
            **{"from": {"model": AGENT_MODEL}},
            to={"model": "claude-sonnet-5"},
            trigger={"type": "refusal"},
        )
        content = [fallback, thinking(), text("a"), tool_use("tu_1", "list_requests", {"q": 1})]
        expected = [block.to_dict() for block in content]
        client = FakeClient([response(content, "tool_use"), response([text("done")], "end_turn")])
        history = copy.deepcopy(USER_MSG)

        outcome = run(client=client, session=FakeSession([READ_A]), messages=history)

        self.assertEqual(outcome.messages[1], {"role": "assistant", "content": expected})
        self.assertEqual(outcome.messages[0], USER_MSG[0])
        # Входной список вызывающего не меняется.
        self.assertEqual(history, USER_MSG)

    def test_usage_priced_per_fallback_iteration(self):
        iterations = [
            SimpleNamespace(
                type="message", model=None, input_tokens=1_000_000, output_tokens=0,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
            SimpleNamespace(
                type="fallback_message", model="claude-sonnet-5", input_tokens=0, output_tokens=1_000_000,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
        ]
        client = FakeClient(
            [response([text("ok")], "end_turn", model="claude-sonnet-5", input_tokens=0, output_tokens=1_000_000, iterations=iterations)]
        )
        outcome = run(client=client, session=FakeSession([]))
        self.assertEqual(outcome.usage.input_tokens, 1_000_000)
        self.assertEqual(outcome.usage.output_tokens, 1_000_000)
        self.assertEqual(outcome.usage.cost_usd, Decimal("12.00"))
        self.assertEqual(outcome.usage.model, "claude-sonnet-5")


# --- MCP-клиент ---------------------------------------------------------


class FakeMcpClient:
    def __init__(self, pages=None, call_result=None, call_error=None):
        self._pages = pages or {}
        self._call_result = call_result
        self._call_error = call_error
        self.cursors = []

    async def list_tools(self, *, cursor=None):
        self.cursors.append(cursor)
        return self._pages[cursor]

    async def call_tool(self, name, arguments=None):
        if self._call_error is not None:
            raise self._call_error
        return self._call_result


class ClientMcpSessionTests(SimpleTestCase):
    def test_list_tools_follows_pagination(self):
        from mcp.types import ListToolsResult, Tool, ToolAnnotations

        schema = {"type": "object"}
        pages = {
            None: ListToolsResult(
                tools=[Tool(name="b", input_schema=schema, annotations=ToolAnnotations(read_only_hint=True))],
                next_cursor="p2",
            ),
            "p2": ListToolsResult(tools=[Tool(name="a", input_schema=schema)], next_cursor=None),
        }
        fake = FakeMcpClient(pages=pages)
        specs = asyncio.run(ClientMcpSession(fake).list_tools())
        self.assertEqual(fake.cursors, [None, "p2"])
        self.assertEqual([(s.name, s.read_only) for s in specs], [("b", True), ("a", False)])

    def test_call_tool_joins_text_and_passes_is_error(self):
        from mcp.types import CallToolResult, TextContent

        result = CallToolResult(content=[TextContent(text="a"), TextContent(text="b")], is_error=True)
        out = asyncio.run(ClientMcpSession(FakeMcpClient(call_result=result)).call_tool("t", {}))
        self.assertEqual(out, ("a\nb", True))

    def test_call_tool_exception_becomes_tool_error(self):
        session = ClientMcpSession(FakeMcpClient(call_error=RuntimeError("down")))
        with self.assertLogs("apps.modules.ai_assistant.mcp_client", level="ERROR"):
            out = asyncio.run(session.call_tool("t", {}))
        self.assertEqual(out, ("Tool error: down", True))

    def test_mint_mcp_access_token_has_tenant_claim_and_short_lifetime(self):
        from rest_framework_simplejwt.tokens import AccessToken

        from apps.accounts.authentication import MCP_TENANT_CLAIM
        from apps.modules.ai_assistant.config import MCP_TOKEN_MINUTES

        user = SimpleNamespace(id=42, pk=42, is_active=True, password="")
        raw = mint_mcp_access_token(user, 7)
        token = AccessToken(raw)
        self.assertEqual(int(token["user_id"]), 42)
        self.assertEqual(token[MCP_TENANT_CLAIM], 7)
        remaining = token["exp"] - time.time()
        self.assertLessEqual(remaining, MCP_TOKEN_MINUTES * 60 + 5)
        self.assertGreater(remaining, (MCP_TOKEN_MINUTES - 1) * 60)
