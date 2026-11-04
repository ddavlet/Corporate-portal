"""Цикл агента: Anthropic Messages API (beta, серверный fallback) + инструменты MCP портала.

Контракт:
- История только дописывается: ответ модели добавляется целиком
  (`response.content` как есть, включая thinking и fallback-блоки).
- Инструменты с read_only выполняются сразу; если модель запросила хотя бы
  один изменяющий инструмент — ничего не выполняется, исход "confirm" с
  pending_tool_calls (все tool_use этого ответа).
- Продолжение после решения пользователя: resume_tool_calls + resume_decision.
- Ошибки API и MCP → исход "error" (в лог), из run_agent ничего не вылетает.
  Ошибка самого инструмента — не ошибка агента: уходит модели как is_error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import anthropic

from .config import (
    AGENT_EFFORT,
    AGENT_MAX_STEPS,
    AGENT_MAX_TOKENS,
    AGENT_MODEL,
    FALLBACK_BETA,
    THINKING_BINDING_BETA,
)
from .mcp_client import McpSession, ToolSpec
from .pricing import cost_usd
from .prompts import SYSTEM_PROMPT

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

CANCELLED_RESULT = "Cancelled by the user."
EMPTY_RESULT = "(empty result)"

# Префикс, к которому привязан thinking-блок, между ходами может меняться (список
# инструментов по роли, описания инструментов после деплоя, порядок ключей jsonb в
# сохранённом tool_use.input). Такие блоки API отбрасывает, а не отвечает 400.
THINKING_CONFIG = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}

# Строки usage.iterations, которые соответствуют попыткам модели (основной и fallback).
_MODEL_ITERATION_TYPES = ("message", "fallback_message")


@dataclass
class TurnUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    mcp_calls: int = 0
    model: str = ""

    def add_response(self, response) -> None:
        """Добавить расход одного ответа API (по попыткам из usage.iterations, если они есть)."""
        for model, inp, out, cache_read, cache_creation in _usage_parts(response):
            self.input_tokens += inp
            self.output_tokens += out
            self.cache_read_tokens += cache_read
            self.cache_creation_tokens += cache_creation
            self.cost_usd += cost_usd(
                model,
                input_tokens=inp,
                output_tokens=out,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
            )
        self.model = str(getattr(response, "model", "") or "")


@dataclass
class AgentOutcome:
    kind: Literal["answer", "confirm", "refused", "error"]
    messages: list[dict]
    text: str = ""
    pending_tool_calls: list[dict] = field(default_factory=list)
    usage: TurnUsage = field(default_factory=TurnUsage)


def _int(value) -> int:
    return int(value or 0)


def _usage_parts(response) -> list[tuple[str, int, int, int, int]]:
    """(model, input, output, cache_read, cache_creation) по каждой попытке модели.

    При серверном fallback верхний usage описывает только попытку, давшую ответ;
    полный расход — в usage.iterations, каждая попытка по цене своей модели.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return []
    response_model = str(getattr(response, "model", "") or AGENT_MODEL)
    iterations = [
        item
        for item in (getattr(usage, "iterations", None) or [])
        if getattr(item, "type", None) in _MODEL_ITERATION_TYPES
    ]
    if iterations:
        return [
            (
                str(getattr(item, "model", None) or AGENT_MODEL),
                _int(getattr(item, "input_tokens", 0)),
                _int(getattr(item, "output_tokens", 0)),
                _int(getattr(item, "cache_read_input_tokens", 0)),
                _int(getattr(item, "cache_creation_input_tokens", 0)),
            )
            for item in iterations
        ]
    return [
        (
            response_model,
            _int(getattr(usage, "input_tokens", 0)),
            _int(getattr(usage, "output_tokens", 0)),
            _int(getattr(usage, "cache_read_input_tokens", 0)),
            _int(getattr(usage, "cache_creation_input_tokens", 0)),
        )
    ]


def _tool_params(specs: list[ToolSpec]) -> list[dict]:
    """Инструменты для API в стабильном порядке (по имени) — ради кеша префикса."""
    return [
        {"name": spec.name, "description": spec.description, "input_schema": spec.input_schema}
        for spec in sorted(specs, key=lambda s: s.name)
    ]


def _is_read_only(by_name: dict[str, ToolSpec], name: str) -> bool:
    spec = by_name.get(name)
    return spec is not None and spec.read_only is True


def _tool_calls(response) -> list[dict]:
    return [
        {"id": block.id, "name": block.name, "input": block.input}
        for block in response.content
        if block.type == "tool_use"
    ]


def _answer_text(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text").strip()


async def _call_tool(session: McpSession, name: str, arguments: dict) -> tuple[str, bool]:
    try:
        return await session.call_tool(name, arguments)
    except Exception as exc:
        logger.exception("ai_assistant agent: MCP tool call raised: tool=%s", name)
        return f"Tool error: {exc}", True


async def _tool_results(
    session: McpSession,
    by_name: dict[str, ToolSpec],
    calls: list[dict],
    usage: TurnUsage,
    *,
    cancel_writes: bool,
) -> dict:
    """Один user-message со всеми tool_result в порядке tool_use."""
    results = []
    for call in calls:
        name = call.get("name", "")
        if cancel_writes and not _is_read_only(by_name, name):
            content, is_error = CANCELLED_RESULT, True
        else:
            content, is_error = await _call_tool(session, name, call.get("input") or {})
            usage.mcp_calls += 1
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": content or EMPTY_RESULT,
                "is_error": bool(is_error),
            }
        )
    return {"role": "user", "content": results}


def _field(item, name: str) -> str:
    value = item.get(name) if isinstance(item, dict) else getattr(item, name, None)
    return str(value or "?")


def _log_input_transformations(response, step: int) -> None:
    """Предупреждение о блоках, которые API отбросил/пропустил при проверке привязки (только счётчики)."""
    entries = getattr(response, "input_transformations", None) or []
    if not entries:
        return
    counts: dict[str, int] = {}
    for entry in entries:
        key = f"{_field(entry, 'type')}/{_field(entry, 'reason')}"
        counts[key] = counts.get(key, 0) + 1
    logger.warning(
        "ai_assistant agent: input_transformations on step %s: %s",
        step,
        ", ".join(f"{key}={count}" for key, count in sorted(counts.items())),
    )


async def _create(client: "AsyncAnthropic", tools: list[dict], messages: list[dict]):
    return await client.beta.messages.create(
        model=AGENT_MODEL,
        max_tokens=AGENT_MAX_TOKENS,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=tools,
        messages=list(messages),
        thinking=THINKING_CONFIG,
        output_config={"effort": AGENT_EFFORT},
        cache_control={"type": "ephemeral"},
        betas=[FALLBACK_BETA, THINKING_BINDING_BETA],
        fallbacks="default",
    )


async def run_agent(
    *,
    client: "AsyncAnthropic",
    session: McpSession,
    messages: list[dict],
    resume_tool_calls: list[dict] | None = None,
    resume_decision: Literal["confirm", "cancel"] | None = None,
) -> AgentOutcome:
    """Довести ход агента до ответа, запроса подтверждения, отказа или ошибки. Не бросает исключений."""
    history = list(messages)
    usage = TurnUsage()

    def outcome(kind, *, text: str = "", pending: list[dict] | None = None) -> AgentOutcome:
        return AgentOutcome(
            kind=kind,
            messages=history,
            text=text,
            pending_tool_calls=pending or [],
            usage=usage,
        )

    try:
        specs = list(await session.list_tools())
    except Exception:
        logger.exception("ai_assistant agent: MCP list_tools failed")
        return outcome("error")
    by_name = {spec.name: spec for spec in specs}
    tools = _tool_params(specs)

    if resume_tool_calls:
        if resume_decision not in ("confirm", "cancel"):
            logger.error("ai_assistant agent: resume without a valid decision: %r", resume_decision)
            return outcome("error")
        history.append(
            await _tool_results(
                session,
                by_name,
                resume_tool_calls,
                usage,
                cancel_writes=resume_decision == "cancel",
            )
        )

    steps = 0
    while True:
        if steps >= AGENT_MAX_STEPS:
            logger.error("ai_assistant agent: step limit reached (%s API calls)", AGENT_MAX_STEPS)
            return outcome("error")
        steps += 1
        try:
            response = await _create(client, tools, history)
        except anthropic.APIError:
            logger.exception("ai_assistant agent: Anthropic API error on step %s", steps)
            return outcome("error")
        except Exception:
            logger.exception("ai_assistant agent: unexpected error calling Anthropic API on step %s", steps)
            return outcome("error")

        try:
            usage.add_response(response)
        except Exception:
            # Учёт расхода не должен ломать ответ пользователю.
            logger.exception("ai_assistant agent: usage accounting failed on step %s", steps)

        _log_input_transformations(response, steps)

        # Полный content без изменений (thinking/fallback-блоки нужны API в истории).
        history.append({"role": "assistant", "content": [block.to_dict() for block in response.content]})
        stop_reason = response.stop_reason
        logger.info(
            "ai_assistant agent: step=%s stop_reason=%s model=%s",
            steps,
            stop_reason,
            getattr(response, "model", ""),
        )

        if stop_reason == "refusal":
            stop_details = getattr(response, "stop_details", None)
            logger.warning(
                "ai_assistant agent: refusal, category=%s",
                getattr(stop_details, "category", None),
            )
            return outcome("refused")

        if stop_reason == "tool_use":
            calls = _tool_calls(response)
            if not calls:
                logger.error("ai_assistant agent: stop_reason=tool_use without tool_use blocks")
                return outcome("error")
            if any(not _is_read_only(by_name, call["name"]) for call in calls):
                return outcome("confirm", pending=calls)
            history.append(await _tool_results(session, by_name, calls, usage, cancel_writes=False))
            continue

        if stop_reason == "pause_turn":
            continue

        if stop_reason in ("end_turn", "stop_sequence"):
            text = _answer_text(response)
            if not text:
                # Пустой ответ (например, только thinking) — иначе пользователь получит тишину.
                logger.warning("ai_assistant agent: stop_reason=%s with empty answer text", stop_reason)
                return outcome("error")
            return outcome("answer", text=text)

        if stop_reason == "max_tokens" and not _tool_calls(response):
            text = _answer_text(response)
            if text:
                logger.warning("ai_assistant agent: answer truncated by max_tokens=%s", AGENT_MAX_TOKENS)
                return outcome("answer", text=text)

        logger.error("ai_assistant agent: unhandled stop_reason=%s", stop_reason)
        return outcome("error")
