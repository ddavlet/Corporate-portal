import copy
import logging
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

from apps.modules.telegram_approvals.models import TelegramMessage, TelegramMessageHistory

from .models import ChainNode

logger = logging.getLogger(__name__)

MAX_DEPTH = 500
TASHKENT = ZoneInfo("Asia/Tashkent")
_ENTITIES = {'"': "&quot;", "'": "&apos;"}
_MATERIALIZE_ACTIONS = (
    TelegramMessageHistory.ACTION_SEND,
    TelegramMessageHistory.ACTION_EDIT,
    TelegramMessageHistory.ACTION_RESEND_NEW,
)


def _esc_text(value) -> str:
    return escape(value or "")


def _esc_attr(value) -> str:
    return escape(value or "", _ENTITIES)


def user_label(user) -> str:
    return (user.get_full_name() or getattr(user, "full_name", "") or user.get_username() or "").strip()


def add_node(
    *,
    tenant,
    chat_id,
    message_id,
    parent_message_id,
    kind,
    text,
    author_user=None,
    author_tg_id=None,
    author_label="",
    author_roles="",
    agent_messages=None,
) -> ChainNode:
    node, _ = ChainNode.objects.get_or_create(
        tenant=tenant,
        chat_id=str(chat_id),
        message_id=message_id,
        defaults={
            "parent_message_id": parent_message_id,
            "kind": kind,
            "text": text or "",
            "author_user": author_user,
            "author_tg_id": author_tg_id,
            "author_label": author_label or "",
            "author_roles": author_roles or "",
            "agent_messages": agent_messages,
        },
    )
    return node


def find_known_node(tenant, chat_id: str, message_id: int):
    chat_id = str(chat_id)
    node = ChainNode.objects.filter(tenant=tenant, chat_id=chat_id, message_id=message_id).first()
    if node is not None:
        return node
    tg_message = TelegramMessage.objects.filter(
        tenant=tenant, recipient_id=chat_id, message_id=message_id
    ).first()
    if tg_message is None:
        return None
    history = (
        TelegramMessageHistory.objects.filter(
            telegram_message=tg_message, success=True, action__in=_MATERIALIZE_ACTIONS
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    node = add_node(
        tenant=tenant,
        chat_id=chat_id,
        message_id=message_id,
        parent_message_id=None,
        kind=ChainNode.KIND_BOT_AUTO,
        text=history.text if history else "",
    )
    if node.created_at != tg_message.sent_at:
        ChainNode.objects.filter(pk=node.pk, kind=ChainNode.KIND_BOT_AUTO, parent_message_id__isnull=True).update(
            created_at=tg_message.sent_at
        )
        node.created_at = tg_message.sent_at
    return node


def ensure_parent(tenant, chat_id: str, event: dict):
    reply_to = event.get("reply_to_message_id")
    if not reply_to:
        return None
    node = find_known_node(tenant, chat_id, reply_to)
    if node is not None:
        return node
    reply_text = event.get("reply_to_text") or ""
    if not reply_text:
        return None
    kind = ChainNode.KIND_BOT_AUTO if event.get("reply_to_is_bot") else ChainNode.KIND_MEMBER
    return add_node(
        tenant=tenant,
        chat_id=chat_id,
        message_id=reply_to,
        parent_message_id=None,
        kind=kind,
        text=reply_text,
        author_label="unknown",
    )


def path_to_root(node: ChainNode) -> list:
    """Root-first list of ancestors ending at `node`; strictly upward, no siblings."""
    path = [node]
    seen = {node.message_id}
    current = node
    while current.parent_message_id is not None:
        if len(path) >= MAX_DEPTH:
            logger.warning("ai_assistant: chain depth limit reached tenant=%s chat=%s", node.tenant_id, node.chat_id)
            break
        if current.parent_message_id in seen:
            logger.warning("ai_assistant: cycle in chain tenant=%s chat=%s", node.tenant_id, node.chat_id)
            break
        parent = ChainNode.objects.filter(
            tenant_id=node.tenant_id, chat_id=node.chat_id, message_id=current.parent_message_id
        ).first()
        if parent is None:
            break
        seen.add(parent.message_id)
        path.append(parent)
        current = parent
    path.reverse()
    return path


def render_user_turn(node: ChainNode) -> str:
    created = node.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=dt_timezone.utc)
    date = created.astimezone(TASHKENT).strftime("%Y-%m-%d")
    return (
        f'<message from="{_esc_attr(node.author_label)}" '
        f'roles="{_esc_attr(node.author_roles or "not_a_portal_user")}" '
        f'date="{date}">{_esc_text(node.text)}</message>'
    )


def _text_turn(role: str, text: str) -> dict:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def build_messages(path: list) -> list:
    start = -1
    for index in range(len(path) - 1, -1, -1):
        if path[index].agent_messages:
            start = index
            break
    messages = copy.deepcopy(path[start].agent_messages) if start >= 0 else []
    for node in path[start + 1 :]:
        if node.kind == ChainNode.KIND_BOT_AGENT:
            messages.append(_text_turn("assistant", node.text))
        elif node.kind == ChainNode.KIND_BOT_AUTO:
            messages.append(_text_turn("assistant", f"<auto_notification>{_esc_text(node.text)}</auto_notification>"))
        else:
            messages.append(_text_turn("user", render_user_turn(node)))
    if messages and messages[0].get("role") == "assistant":
        messages.insert(0, _text_turn("user", "<conversation_start/>"))
    return messages
