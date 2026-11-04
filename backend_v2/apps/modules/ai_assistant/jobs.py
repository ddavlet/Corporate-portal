import asyncio
import logging
import time
from datetime import timedelta

from concurrent.futures import ThreadPoolExecutor

from anthropic import AsyncAnthropic
from django.db import close_old_connections, transaction
from django.utils import timezone

from .access import assistant_enabled, resolve_assistant_user
from .agent import TurnUsage, run_agent
from .chain import add_node, build_messages, path_to_root
from .config import AGENT_MODEL, CONFIRMATION_TTL_HOURS, EXECUTOR_MAX_WORKERS
from .mcp_client import mint_mcp_access_token, open_mcp
from .models import ChainNode, PendingConfirmation, UsageRecord
from .telegram_out import (
    render_confirmation,
    send_answer,
    send_confirmation,
    send_typing,
    split_message,
    to_telegram_html,
)

logger = logging.getLogger(__name__)

ERROR_TEXT = "Не получилось ответить, попробуйте позже."
REFUSED_TEXT = "Не могу ответить на этот вопрос."

_executor = ThreadPoolExecutor(max_workers=EXECUTOR_MAX_WORKERS, thread_name_prefix="ai-assistant")


def _safe(func):
    """Обёртка для executor: ошибка задачи всегда попадает в лог, а не пропадает молча."""

    def wrapper(*args):
        try:
            func(*args)
        except Exception:
            logger.exception("ai_assistant: background job %s failed", getattr(func, "__name__", "?"))

    return wrapper


def submit_turn(node_id: int) -> None:
    """Запустить ход агента в фоне после коммита текущей транзакции."""
    transaction.on_commit(lambda: _executor.submit(_safe(run_turn), node_id))


def submit_resume(pending_id: int, decision: str) -> None:
    """Продолжить приостановленный ход после «Подтвердить»/«Отменить»."""
    transaction.on_commit(lambda: _executor.submit(_safe(resume_pending), pending_id, decision))


async def _agent_job(*, subdomain, token, messages, resume_tool_calls=None, resume_decision=None):
    """Только MCP и Anthropic; возвращает обычные данные (ORM здесь не трогаем)."""
    async with AsyncAnthropic() as client:
        async with open_mcp(tenant_subdomain=subdomain, token=token) as session:
            outcome = await run_agent(
                client=client,
                session=session,
                messages=messages,
                resume_tool_calls=resume_tool_calls,
                resume_decision=resume_decision,
            )
            descriptions: dict[str, str] = {}
            if outcome.kind == "confirm":
                tools = await session.list_tools()
                descriptions = {tool.name: tool.description for tool in tools}
            return outcome, descriptions


def _send_error(tenant, chat_id, reply_to_message_id) -> None:
    try:
        send_answer(tenant, chat_id, reply_to_message_id, ERROR_TEXT)
    except Exception:
        logger.exception("ai_assistant: failed to send error text chat_id=%s", chat_id)


def _deliver_answer(tenant, chat_id, reply_to_message_id, outcome) -> None:
    sent = send_answer(tenant, chat_id, reply_to_message_id, outcome.text)
    parts = split_message(to_telegram_html(outcome.text))
    if not sent:
        logger.warning("ai_assistant: answer was not delivered chat_id=%s", chat_id)
    parent = reply_to_message_id
    for message, part in zip(sent, parts):
        add_node(
            tenant=tenant,
            chat_id=chat_id,
            message_id=message.message_id,
            parent_message_id=parent,
            kind=ChainNode.KIND_BOT_AGENT,
            text=part,
            agent_messages=outcome.messages,
        )
        parent = message.message_id


def _deliver_confirmation(tenant, chat_id, reply_to_message_id, *, user, tg_id, origin_message_id, outcome, descriptions):
    pending = PendingConfirmation.objects.create(
        tenant=tenant,
        chat_id=str(chat_id),
        requester_user=user,
        requester_tg_id=tg_id,
        origin_message_id=origin_message_id,
        agent_messages=outcome.messages,
        tool_calls=outcome.pending_tool_calls,
        expires_at=timezone.now() + timedelta(hours=CONFIRMATION_TTL_HOURS),
    )
    text = render_confirmation(outcome.pending_tool_calls, descriptions)
    try:
        message = send_confirmation(tenant, chat_id, reply_to_message_id, pending.pk, text)
    except Exception:
        _close_pending(pending)
        raise
    if message is None:
        _close_pending(pending)
        raise RuntimeError("confirmation message was not sent")
    pending.confirmation_message = message
    pending.save(update_fields=["confirmation_message"])
    add_node(
        tenant=tenant,
        chat_id=chat_id,
        message_id=message.message_id,
        parent_message_id=reply_to_message_id,
        kind=ChainNode.KIND_BOT_AGENT,
        text=text,
        agent_messages=None,
    )


def _close_pending(pending) -> None:
    pending.status = PendingConfirmation.STATUS_CANCELLED
    pending.resolved_at = timezone.now()
    pending.save(update_fields=["status", "resolved_at"])


def _execute(
    *,
    tenant,
    user,
    tg_id,
    chat_id,
    reply_to_message_id,
    origin_message_id,
    prepare,
    resume_tool_calls=None,
    resume_decision=None,
) -> None:
    """Общая часть run_turn и resume_pending. `prepare()` отдаёт messages (ORM, до event loop)."""
    started = time.monotonic()
    outcome = None
    descriptions: dict[str, str] = {}
    usage_outcome = UsageRecord.OUTCOME_ERROR
    try:
        try:
            if user is None:
                raise ValueError("no portal user for the turn")
            messages = prepare()
            token = mint_mcp_access_token(user, tenant.pk)
            outcome, descriptions = asyncio.run(
                _agent_job(
                    subdomain=tenant.subdomain,
                    token=token,
                    messages=messages,
                    resume_tool_calls=resume_tool_calls,
                    resume_decision=resume_decision,
                )
            )
        except Exception:
            logger.exception("ai_assistant: agent run failed tenant=%s chat_id=%s", tenant.pk, chat_id)
            outcome = None

        try:
            if outcome is None or outcome.kind == "error":
                if outcome is not None:
                    logger.error("ai_assistant: agent ended with error tenant=%s chat_id=%s", tenant.pk, chat_id)
                _send_error(tenant, chat_id, reply_to_message_id)
            elif outcome.kind == "refused":
                usage_outcome = UsageRecord.OUTCOME_REFUSED
                send_answer(tenant, chat_id, reply_to_message_id, REFUSED_TEXT)
            elif outcome.kind == "confirm":
                usage_outcome = UsageRecord.OUTCOME_CONFIRMATION_REQUESTED
                _deliver_confirmation(
                    tenant,
                    chat_id,
                    reply_to_message_id,
                    user=user,
                    tg_id=tg_id,
                    origin_message_id=origin_message_id,
                    outcome=outcome,
                    descriptions=descriptions,
                )
            else:
                usage_outcome = UsageRecord.OUTCOME_ANSWERED
                _deliver_answer(tenant, chat_id, reply_to_message_id, outcome)
        except Exception:
            logger.exception("ai_assistant: failed to deliver result tenant=%s chat_id=%s", tenant.pk, chat_id)
            usage_outcome = UsageRecord.OUTCOME_ERROR
            _send_error(tenant, chat_id, reply_to_message_id)

        usage = outcome.usage if outcome is not None else TurnUsage()
        UsageRecord.objects.create(
            tenant=tenant,
            user=user,
            chat_id=str(chat_id),
            model=usage.model or AGENT_MODEL,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
            cost_usd=usage.cost_usd,
            mcp_calls=usage.mcp_calls,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome=usage_outcome,
        )
    finally:
        close_old_connections()


def run_turn(node_id: int) -> None:
    close_old_connections()
    try:
        node = ChainNode.objects.select_related("tenant", "author_user").filter(pk=node_id).first()
        if node is None:
            logger.warning("ai_assistant: chain node %s not found, turn skipped", node_id)
            return
        send_typing(node.tenant, node.chat_id)
        _execute(
            tenant=node.tenant,
            user=node.author_user,
            tg_id=node.author_tg_id,
            chat_id=node.chat_id,
            reply_to_message_id=node.message_id,
            origin_message_id=node.message_id,
            prepare=lambda: build_messages(path_to_root(node)),
        )
    finally:
        close_old_connections()


def resume_pending(pending_id: int, decision: str) -> None:
    close_old_connections()
    try:
        pending = (
            PendingConfirmation.objects.select_related("tenant", "requester_user", "confirmation_message")
            .filter(pk=pending_id)
            .first()
        )
        if pending is None:
            logger.warning("ai_assistant: pending confirmation %s not found, resume skipped", pending_id)
            return
        tenant = pending.tenant
        access = resolve_assistant_user(tenant, pending.requester_tg_id)
        if not (
            assistant_enabled(tenant)
            and access.reason == "ok"
            and access.user is not None
            and access.user.pk == pending.requester_user_id
        ):
            logger.warning(
                "ai_assistant: resume of pending=%s skipped, requester has no access any more", pending_id
            )
            return
        message = pending.confirmation_message
        reply_to = message.message_id if message is not None else pending.origin_message_id
        send_typing(tenant, pending.chat_id)
        _execute(
            tenant=tenant,
            user=pending.requester_user,
            tg_id=pending.requester_tg_id,
            chat_id=pending.chat_id,
            reply_to_message_id=reply_to,
            origin_message_id=pending.origin_message_id,
            prepare=lambda: pending.agent_messages,
            resume_tool_calls=pending.tool_calls,
            resume_decision=decision,
        )
    finally:
        close_old_connections()
